import unittest
from unittest.mock import patch
from tests import test_mobile_invoice_upload as fixtures
from extensions import db
from models import ReimbursementInvoice, UsageLog


class RecognitionTests(unittest.TestCase):
    setUp = fixtures.MobileInvoiceTests.setUp
    challenge = fixtures.MobileInvoiceTests.challenge
    login = fixtures.MobileInvoiceTests.login
    upload = fixtures.MobileInvoiceTests.upload

    def prepare(self, kind="invoice"):
        headers = self.login()
        row = self.upload(headers, kind=kind).json["invoice"]
        return headers, row["id"]

    def values(self, headers, id, policy="review"):
        detail = self.mobile.get(f"/api/mobile/invoices/{id}", headers=headers).json
        refs = self.mobile.get("/api/mobile/bootstrap", headers=headers).json
        return dict(
            snapshot=detail["snapshot"],
            confirmed=True,
            invoice_number="1234567890",
            invoice_date="2026-06-03",
            vendor="测试商家",
            description="办公用品",
            amount="100.00",
            tax_amount="6.00",
            total_amount="106.00",
            inclusion_policy=policy,
            category_id=next(
                c["id"] for c in refs["categories"] if c["name"] == "办公费"
            ),
            product_line_id=refs["product_lines"][0]["id"],
        )

    def test_ocr_is_cached_suggestion_without_financial_write_then_confirm_shared(self):
        headers, id = self.prepare()
        with patch(
            "tools.reimbursement.recognize_original",
            return_value=(
                {
                    "invoice_number": "123",
                    "seller_name": "商家",
                    "total_amount": "106",
                    "amount_excluding_tax": "100",
                    "tax_amount": "6",
                    "invoice_date": "2026-06-03",
                },
                "baidu",
            ),
        ) as provider:
            first = self.mobile.post(
                f"/api/mobile/invoices/{id}/recognize", headers=headers, json={}
            )
            self.assertEqual(first.status_code, 200, first.json)
            self.assertTrue(first.json["success"])
            self.assertEqual(first.json["draft"]["vendor"], "商家")
            self.assertTrue(
                self.mobile.post(
                    f"/api/mobile/invoices/{id}/recognize", headers=headers, json={}
                ).json["cached"]
            )
            self.assertEqual(provider.call_count, 1)
        with self.app.app_context():
            self.assertEqual(db.session.get(ReimbursementInvoice, id).total_amount, 0)
            self.assertEqual(UsageLog.query.count(), 2)  # upload and one successful OCR
        body = self.values(headers, id, "expense")
        saved = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json["invoice"]["vendor"], "测试商家")
        self.assertEqual(
            self.web.get(f"/tools/reimbursement/api/summary/{self.period}").json[
                "summary"
            ]["total_amount"],
            106,
        )
        self.assertEqual(
            self.mobile.post(
                f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
            ).status_code,
            409,
        )

    def test_amount_mismatch_and_expense_fuel_rejected_retain_keeps_summary(self):
        headers, id = self.prepare("fuel")
        body = self.values(headers, id, "retain")
        bad = {**body, "total_amount": "107"}
        self.assertEqual(
            self.mobile.post(
                f"/api/mobile/invoices/{id}/confirm", headers=headers, json=bad
            ).status_code,
            400,
        )
        self.assertEqual(
            self.mobile.post(
                f"/api/mobile/invoices/{id}/confirm",
                headers=headers,
                json={**body, "inclusion_policy": "expense"},
            ).status_code,
            400,
        )
        result = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(
            self.web.get(f"/tools/reimbursement/api/summary/{self.period}").json[
                "summary"
            ]["total_amount"],
            0,
        )

    def test_failed_ocr_is_manual_draft_no_charge_and_owner_enforced(self):
        headers, id = self.prepare()
        with patch("tools.reimbursement.recognize_original", return_value=(None, None)):
            result = self.mobile.post(
                f"/api/mobile/invoices/{id}/recognize", headers=headers, json={}
            )
            self.assertFalse(result.json["success"])
        with self.app.app_context():
            self.assertEqual(UsageLog.query.count(), 1)
        with self.web.session_transaction() as session:
            session["_user_id"] = "2"
        other = self.login(subject="other")
        self.assertEqual(
            self.mobile.get(f"/api/mobile/invoices/{id}", headers=other).status_code,
            404,
        )
        self.assertEqual(
            self.mobile.post(
                f"/api/mobile/invoices/{id}/recognize", headers=other, json={}
            ).status_code,
            404,
        )

    def test_metadata_invalid_fields_rejected_and_confirmation_explicit(self):
        headers, id = self.prepare()
        body = self.values(headers, id)
        for update in (
            {"confirmed": False},
            {"office_id": []},
            {"file_url": "https://bad.invalid"},
            {"invoice_date": "bad"},
            {"tax_amount": "NaN"},
        ):
            self.assertEqual(
                self.mobile.post(
                    f"/api/mobile/invoices/{id}/confirm",
                    headers=headers,
                    json={**body, **update},
                ).status_code,
                400,
                update,
            )

    def test_successful_ocr_cache_survives_period_transfer(self):
        headers, id = self.prepare()
        with patch(
            "tools.reimbursement.recognize_original",
            return_value=({"invoice_number": "123"}, "test"),
        ) as provider:
            self.mobile.post(
                f"/api/mobile/invoices/{id}/recognize", headers=headers, json={}
            )
            period = self.web.post(
                "/tools/reimbursement/api/periods",
                json={
                    "start_year": 2026,
                    "start_month": 8,
                    "end_year": 2026,
                    "end_month": 9,
                },
            ).json["period"]["id"]
            body = self.values(headers, id)
            body["period_id"] = period
            self.assertEqual(
                self.mobile.post(
                    f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
                ).status_code,
                200,
            )
            result = self.mobile.post(
                f"/api/mobile/invoices/{id}/recognize", headers=headers, json={}
            )
            self.assertTrue(result.json["cached"])
            self.assertEqual(provider.call_count, 1)

    def test_confirm_updates_generated_detail_amount_without_erasing_manual_participants(
        self,
    ):
        import json
        from models import ReimbursementAuxDetail

        headers, id = self.prepare()
        body = self.values(headers, id, "expense")
        refs = self.mobile.get("/api/mobile/bootstrap", headers=headers).json
        body["category_id"] = refs["categories"][0]["id"]
        self.assertEqual(
            self.mobile.post(
                f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
            ).status_code,
            200,
        )
        with self.app.app_context():
            row = ReimbursementAuxDetail.query.first()
            data = json.loads(row.data_json)
            data["participants"] = "已填写参与人"
            row.data_json = json.dumps(data)
            db.session.commit()
        body["snapshot"] = self.mobile.get(
            f"/api/mobile/invoices/{id}", headers=headers
        ).json["snapshot"]
        body.update(
            amount="200", tax_amount="12", total_amount="212", invoice_date="2026-06-04"
        )
        saved = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(saved.status_code, 200, saved.json)
        with self.app.app_context():
            data = json.loads(ReimbursementAuxDetail.query.first().data_json)
            self.assertEqual(
                (data["amount"], data["date"], data["participants"]),
                (212, "2026-06-04", "已填写参与人"),
            )

    def test_separately_adjusted_detail_requires_website_instead_of_silent_overwrite(
        self,
    ):
        import json
        from models import ReimbursementAuxDetail

        headers, id = self.prepare()
        body = self.values(headers, id, "expense")
        body["category_id"] = self.mobile.get(
            "/api/mobile/bootstrap", headers=headers
        ).json["categories"][0]["id"]
        self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        with self.app.app_context():
            row = ReimbursementAuxDetail.query.first()
            data = json.loads(row.data_json)
            data["amount"] = 50
            row.data_json = json.dumps(data)
            db.session.commit()
        body["snapshot"] = self.mobile.get(
            f"/api/mobile/invoices/{id}", headers=headers
        ).json["snapshot"]
        body.update(amount="200", tax_amount="12", total_amount="212")
        self.assertEqual(
            self.mobile.post(
                f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
            ).status_code,
            409,
        )
        with self.app.app_context():
            self.assertEqual(db.session.get(ReimbursementInvoice, id).total_amount, 106)

    def test_remarks_preserve_independent_amount_and_date(self):
        import json
        from models import ReimbursementAuxDetail

        headers, id = self.prepare()
        body = self.values(headers, id, "expense")
        body["category_id"] = self.mobile.get(
            "/api/mobile/bootstrap", headers=headers
        ).json["categories"][0]["id"]
        self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        with self.app.app_context():
            row = ReimbursementAuxDetail.query.first()
            data = json.loads(row.data_json)
            data.update(amount=50, date="")
            row.data_json = json.dumps(data)
            db.session.commit()
        body["snapshot"] = self.mobile.get(
            f"/api/mobile/invoices/{id}", headers=headers
        ).json["snapshot"]
        body["remarks"] = "仅备注修改"
        saved = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(saved.status_code, 200, saved.json)
        with self.app.app_context():
            data = json.loads(ReimbursementAuxDetail.query.first().data_json)
            self.assertEqual((data["amount"], data["date"]), (50, ""))
