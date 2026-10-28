import json
import unittest
from decimal import Decimal
from flask import Blueprint, Flask
from extensions import db, login_manager
from models import ReimbursementAttachment, ReimbursementAuxDetail, ReimbursementInvoice
from tools.reimbursement.manager import register_routes, _cover_payload, _summary
from tools.reimbursement.retention import allocate, money, month


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY="test", TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
        db.init_app(self.app)
        login_manager.init_app(self.app)
        login_manager.user_loader(lambda _: None)
        bp = Blueprint("retention_test", __name__, url_prefix="/rb")
        register_routes(bp)
        self.app.register_blueprint(bp)
        with self.app.app_context():
            db.create_all()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["anon_id"] = "retention-owner"
        data = self.client.get("/rb/api/bootstrap").get_json()
        self.office = data["offices"][0]["id"]
        self.category = data["categories"][0]["id"]
        self.period = self.client.post("/rb/api/periods", json=dict(start_year=2026, start_month=6,
            end_year=2026, end_month=7)).get_json()["period"]["id"]

    def invoice(self, **kwargs):
        return self.client.post("/rb/api/invoices", json=dict(period_id=self.period,
            office_id=self.office, category_id=self.category, **kwargs))

    def statement(self):
        with self.app.app_context():
            db.session.add(ReimbursementAttachment(owner_type="anon", owner_id="retention-owner",
                stored_name="123456789abc.pdf", original_name="账单.pdf", mime_type="application/pdf",
                content=b"test", file_size=4))
            db.session.commit()
        response = self.invoice(document_kind="toll_statement", total_amount="590.48", amount_confirmed=True,
            occurrence_month="2026-06", file_url="/tools/reimbursement/preview/123456789abc.pdf")
        self.assertEqual(response.status_code, 201)
        return response.get_json()["invoice"]

    def vehicles(self):
        response = self.client.put(f"/rb/api/aux/{self.period}", json={"vehicle":[
            {"date":"2026-06-01", "km_total":10}, {"date":"2026-06-02", "km_total":20},
            {"date":"2026-07-01", "km_total":30}]})
        self.assertEqual(response.status_code, 200)
        return [row["id"] for row in response.get_json()["aux"]["vehicle"]]

    def test_integer_cents_and_fallback(self):
        for weights in ([1, 1, 1], [2, 5, 8], [0, 8, 3], [None, 7]):
            result = allocate("590.48", weights)
            self.assertEqual(sum(map(Decimal, result)), Decimal("590.48"))
        self.assertEqual(allocate("0.01", [1, 1, 1]), ["0", "0", "0.01"])
        self.assertEqual(allocate("10", [0, 8]), ["5", "5"])

    def test_invalid_money_and_month(self):
        for value in ("NaN", "Infinity", "-1", "1.001", "1000000000", [], "abc"):
            with self.assertRaises(ValueError): money(value)
        for value in ("2026-13", "2026-1", "2026-00", None):
            with self.assertRaises(ValueError): month(value)

    def test_retained_and_review_excluded_from_every_summary(self):
        self.assertEqual(self.invoice(total_amount="100", amount="100").status_code, 201)
        for policy in ("retain", "review"):
            self.assertEqual(self.invoice(inclusion_policy=policy, total_amount="999", amount="999").status_code, 201)
        summary = self.client.get(f"/rb/api/summary/{self.period}").get_json()["summary"]
        bootstrap = self.client.get("/rb/api/bootstrap").get_json()
        self.assertEqual(summary["total_amount"], 100)
        self.assertEqual(bootstrap["stats"]["total_amount"], 100)
        self.assertEqual(bootstrap["periods"][0]["total_amount"], 100)
        with self.app.test_request_context():
            from models import ReimbursementPeriod
            period = db.session.get(ReimbursementPeriod, self.period)
            self.assertEqual(_cover_payload(period)["total_all"], _summary(period)["total_amount"])

    def test_threshold_and_unknown(self):
        for amount, confirmed, selected in (("4.99", True, False), ("5", True, True), ("20.4", True, True), ("", False, False)):
            response = self.invoice(document_kind="toll", total_amount=amount, amount_confirmed=confirmed)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()["invoice"]["print_selected"], selected)

    def test_fuel_cannot_be_expense_and_cannot_link_detail(self):
        self.assertEqual(self.invoice(document_kind="fuel", inclusion_policy="expense").status_code, 400)
        response = self.invoice(document_kind="fuel", linked_detail={"amount":800})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["invoice"]["inclusion_policy"], "retain")
        with self.app.app_context(): self.assertEqual(ReimbursementAuxDetail.query.count(), 0)

    def test_preview_manual_allocation_conflict_undo_and_audit(self):
        bill = self.statement()
        ids = self.vehicles()
        path = f"/rb/api/periods/{self.period}/toll-allocation"
        request = dict(statement_id=bill["id"], row_ids=ids[:2])
        preview = self.client.post(path, json=request).get_json()
        self.assertEqual(sum(Decimal(r["amount"]) for r in preview["rows"]), Decimal("590.48"))
        request.update(snapshot=preview["snapshot"], statement_snapshot=preview["statement_snapshot"], confirm=True)
        self.assertEqual(self.client.post(path, json={**request, "amounts":["1", "2"]}).status_code, 400)
        response = self.client.post(path, json={**request, "amounts":["200", "390.48"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post(path, json=request).status_code, 409)
        self.assertEqual(self.client.post(path, json={"statement_id":bill["id"], "row_ids":[ids[0]]}).status_code, 409)
        self.assertEqual(self.client.put(f'/rb/api/invoices/{bill["id"]}', json=bill).status_code, 409)
        self.assertEqual(self.client.delete(f'/rb/api/invoices/{bill["id"]}').status_code, 409)
        entries = self.client.get(f"/rb/api/periods/{self.period}/audits").get_json()["audits"]
        entry = next(a for a in entries if a["action"] == "toll.allocate")
        self.assertEqual(self.client.post(path+"/undo", json={"audit_id":entry["id"]}).status_code, 200)
        self.assertEqual(self.client.post(path+"/undo", json={"audit_id":entry["id"]}).status_code, 409)

    def test_month_owner_and_period_boundaries(self):
        bill = self.statement()
        ids = self.vehicles()
        path = f"/rb/api/periods/{self.period}/toll-allocation"
        self.assertEqual(self.client.post(path, json={"statement_id":bill["id"], "row_ids":ids}).status_code, 400)
        other = self.app.test_client()
        self.assertEqual(other.post(path, json={"statement_id":bill["id"], "row_ids":ids[:1]}).status_code, 404)
        self.assertEqual(other.get(f"/rb/api/periods/{self.period}/audits").status_code, 404)
        self.assertEqual(self.client.post(path, json={"statement_id":bill["id"], "row_ids":[9999]}).status_code, 400)

    def test_retention_policy_removes_linked_details(self):
        response = self.invoice(total_amount="80", linked_detail={"amount":80})
        invoice = response.get_json()["invoice"]
        update = self.client.put(f'/rb/api/invoices/{invoice["id"]}', json={**invoice,
            "office_id":self.office, "inclusion_policy":"retain"})
        self.assertEqual(update.status_code, 200)
        with self.app.app_context(): self.assertEqual(ReimbursementAuxDetail.query.count(), 0)

    def test_statement_duplicate_reuses_existing_and_never_crosses_owner(self):
        bill = self.statement()
        response = self.invoice(document_kind="toll_statement", total_amount="590.48", amount_confirmed=True,
            occurrence_month="2026-06", file_url=bill["file_url"])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["duplicate"])
        self.assertEqual(self.invoice(document_kind="toll", file_url="https://example.com/other.pdf").status_code, 400)
