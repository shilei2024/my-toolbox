import json
from decimal import Decimal
import unittest
from tests import test_mobile_invoice_upload as fixtures
from extensions import db
from models import ReimbursementAuxDetail


class DispatchTests(unittest.TestCase):
    setUp = fixtures.MobileInvoiceTests.setUp
    challenge = fixtures.MobileInvoiceTests.challenge
    login = fixtures.MobileInvoiceTests.login

    def setup_dispatch(self):
        headers = self.login()
        refs = self.mobile.get("/api/mobile/bootstrap", headers=headers).json
        return (
            headers,
            refs["product_lines"][0]["name"],
            f"/api/mobile/dispatch/{self.period}",
        )

    def row(self, line, **fields):
        return dict(
            id=None,
            date="2026-06-01",
            from_location="A",
            to_location="B",
            contact="C",
            km_start="100",
            km_total="10",
            toll_fee="1.25",
            parking_fee="2.75",
            product_line=line,
            **fields,
        )

    def test_vehicle_sync_preserves_other_details_snapshot_and_dashboard(self):
        headers, line, path = self.setup_dispatch()
        with self.app.app_context():
            detail = ReimbursementAuxDetail(
                owner_type="user",
                owner_id="1",
                period_id=self.period,
                kind="entertainment",
                sort_order=0,
                data_json=json.dumps({"date": "2026-06-01", "participants": "已录入"}),
            )
            db.session.add(detail)
            db.session.commit()
            other_id = detail.id
        old = self.mobile.get(path, headers=headers).json
        saved = self.mobile.put(
            path,
            headers=headers,
            json={"snapshot": old["snapshot"], "rows": [self.row(line)]},
        )
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json["rows"][0]["km_end"], 110)
        self.assertEqual(
            self.mobile.put(
                path, headers=headers, json={"snapshot": old["snapshot"], "rows": []}
            ).status_code,
            409,
        )
        site = self.web.get(f"/tools/reimbursement/api/summary/{self.period}").json
        self.assertEqual(site["aux"]["vehicle"][0]["id"], saved.json["rows"][0]["id"])
        dashboard = self.mobile.get(
            f"/api/mobile/dashboard/{self.period}", headers=headers
        ).json
        self.assertEqual(
            Decimal(dashboard["total_amount"]),
            Decimal(str(site["summary"]["total_amount"])),
        )
        with self.app.app_context():
            self.assertEqual(
                json.loads(db.session.get(ReimbursementAuxDetail, other_id).data_json)[
                    "participants"
                ],
                "已录入",
            )

    def test_allocated_rows_keep_ids_metadata_and_reject_changes(self):
        headers, line, path = self.setup_dispatch()
        with self.app.app_context():
            data = self.row(line)
            data.pop("id")
            data["toll_statement_id"] = 123
            detail = ReimbursementAuxDetail(
                owner_type="user",
                owner_id="1",
                period_id=self.period,
                kind="vehicle",
                sort_order=0,
                data_json=json.dumps(data),
            )
            db.session.add(detail)
            db.session.commit()
            id = detail.id
        state = self.mobile.get(path, headers=headers).json
        newer = self.row(line)
        newer["date"] = "2026-07-01"
        newer["km_start"] = ""
        saved = self.mobile.put(
            path,
            headers=headers,
            json={"snapshot": state["snapshot"], "rows": state["rows"] + [newer]},
        )
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json["rows"][0]["id"], id)
        self.assertEqual(
            self.mobile.put(
                path,
                headers=headers,
                json={"snapshot": saved.json["snapshot"], "rows": []},
            ).status_code,
            409,
        )
        with self.app.app_context():
            self.assertEqual(
                json.loads(db.session.get(ReimbursementAuxDetail, id).data_json)[
                    "toll_statement_id"
                ],
                123,
            )

    def test_owner_invalid_values_and_client_metadata_rejected(self):
        headers, line, path = self.setup_dispatch()
        state = self.mobile.get(path, headers=headers).json
        for change in (
            {"km_total": "NaN"},
            {"date": "bad"},
            {"toll_statement_id": 1},
            {"id": True},
            {"product_line": "外部目录"},
        ):
            row = self.row(line)
            row.update(change)
            self.assertEqual(
                self.mobile.put(
                    path,
                    headers=headers,
                    json={"snapshot": state["snapshot"], "rows": [row]},
                ).status_code,
                400,
                change,
            )
        with self.web.session_transaction() as session:
            session["_user_id"] = "2"
        other = self.login(subject="other")
        self.assertEqual(self.mobile.get(path, headers=other).status_code, 404)
        self.assertEqual(
            self.mobile.get(
                f"/api/mobile/dashboard/{self.period}", headers=other
            ).status_code,
            404,
        )
