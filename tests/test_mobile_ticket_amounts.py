"""Regression for total-only train receipts; no real tickets/providers required."""
import json
import unittest
from unittest.mock import patch
from tests import test_mobile_recognition as fixtures
from extensions import db
from models import ReimbursementInvoice
from tools.reimbursement.models import ReimbursementAudit
from tools.reimbursement.retention import complete_invoice_amounts


class TicketAmountRulesTests(unittest.TestCase):
    def test_complete_only_missing_values_and_keep_explicit_zero(self):
        cases = [
            (("", "", "590.48"), ("590.48", "0.00", "590.48")),
            ((None, None, "0"), ("0.00", "0.00", "0.00")),
            ((" ", "6", "106"), ("100.00", "6.00", "106.00")),
            (("100", "", "106"), ("100.00", "6.00", "106.00")),
            (("100", "6", ""), ("100.00", "6.00", "106.00")),
            (("0", "0", "106"), ("0.00", "0.00", "106.00")),
            (("", "", ""), ("", "", "")),
        ]
        for values, expected in cases:
            with self.subTest(values=values):
                completed, note = complete_invoice_amounts(dict(zip(("amount", "tax_amount", "total_amount"), values)))
                self.assertEqual(tuple(completed.values()), expected)
                if values[0] is None or values[:2] == ("", "") and values[2]:
                    self.assertIn("暂记0", note)
        for fields in ({"amount":"NaN"}, {"tax_amount":True}, {"tax_amount":"200", "total_amount":"100"},
                       {"amount":"999999999.99", "tax_amount":"0.01"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                complete_invoice_amounts(fields)


class TicketAmountApiTests(unittest.TestCase):
    setUp = fixtures.RecognitionTests.setUp
    challenge = fixtures.RecognitionTests.challenge
    login = fixtures.RecognitionTests.login
    upload = fixtures.RecognitionTests.upload
    prepare = fixtures.RecognitionTests.prepare
    values = fixtures.RecognitionTests.values

    def test_total_only_ocr_cache_and_confirmation_share_website_and_excel(self):
        headers, invoice_id = self.prepare()
        path = f"/api/mobile/invoices/{invoice_id}"
        with patch("tools.reimbursement.recognize_original", return_value=({
            "seller_name":"中国铁路", "description":"火车票", "total_amount":"590.48",
            "invoice_date":"2026-06-03"}, "synthetic")) as provider:
            recognized = self.mobile.post(path+"/recognize", headers=headers, json={})
            self.assertEqual(recognized.status_code, 200, recognized.json)
            self.assertEqual(recognized.json["draft"]["amount"], "590.48")
            self.assertEqual(recognized.json["draft"]["tax_amount"], "0.00")
            self.assertIn("暂记0", recognized.json["amount_note"])
            cached = self.mobile.post(path+"/recognize", headers=headers, json={})
            self.assertTrue(cached.json["cached"])
            self.assertEqual(cached.json["amount_note"], recognized.json["amount_note"])
            self.assertEqual(provider.call_count, 1)
        with self.app.app_context():
            self.assertEqual(db.session.get(ReimbursementInvoice, invoice_id).total_amount, 0)
        body = {**self.values(headers, invoice_id, "expense"), **recognized.json["draft"]}
        refs=self.mobile.get("/api/mobile/bootstrap",headers=headers).json
        body["category_id"]=next(c["id"] for c in refs["categories"] if c["export_key"]=="travel_transport")
        saved = self.mobile.post(path+"/confirm", headers=headers, json=body)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json["invoice"]["total_amount"], 590.48)
        summary = self.web.get(f"/tools/reimbursement/api/summary/{self.period}").json["summary"]
        self.assertEqual(summary["total_amount"], 590.48)
        self.assertEqual(summary["tax_amount"], 0)
        import xlrd
        exported = self.web.get(f"/tools/reimbursement/api/export/details/{self.period}")
        self.assertEqual(exported.status_code, 200)
        book = xlrd.open_workbook(file_contents=exported.data)
        self.assertTrue(any(sheet.cell_value(r,c) == 590.48 for sheet in book.sheets()
            for r in range(sheet.nrows) for c in range(sheet.ncols)))
        # It is an entry validation issue, never an authentication failure.
        self.assertEqual(self.mobile.get("/api/mobile/bootstrap", headers=headers).status_code, 200)

    def test_old_cached_draft_and_old_client_blank_components_work_without_reocr(self):
        headers, invoice_id = self.prepare()
        path=f"/api/mobile/invoices/{invoice_id}"
        with patch("tools.reimbursement.recognize_original", return_value=({"total_amount":"200"}, "synthetic")):
            self.mobile.post(path+"/recognize", headers=headers, json={})
        with self.app.app_context():
            audit=ReimbursementAudit.query.filter_by(action="invoice.ocr").one()
            data=json.loads(audit.data_json)
            data.pop("amount_note", None)
            data["draft"].update(amount="", tax_amount="")
            audit.data_json=json.dumps(data)
            db.session.commit()
        with patch("tools.reimbursement.recognize_original", side_effect=AssertionError("must use cache")):
            cached=self.mobile.post(path+"/recognize", headers=headers, json={})
        self.assertEqual(cached.json["draft"]["amount"], "200.00")
        self.assertIn("暂记0", cached.json["amount_note"])
        body=self.values(headers, invoice_id, "expense")
        body.update(amount="", tax_amount="", total_amount="200")
        saved=self.mobile.post(path+"/confirm", headers=headers, json=body)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json["invoice"]["amount"], 200)
        with self.app.app_context():
            audit=ReimbursementAudit.query.filter_by(action="invoice.confirm").one()
            self.assertIn("暂记0", json.loads(audit.data_json)["amount_note"])

    def test_partial_components_complete_but_explicit_mismatch_and_invalid_rejected(self):
        headers, invoice_id=self.prepare()
        path=f"/api/mobile/invoices/{invoice_id}"
        body=self.values(headers, invoice_id, "expense")
        for change in (dict(amount="0",tax_amount="0",total_amount="106"),
                       dict(amount="",tax_amount="200",total_amount="106"),
                       dict(amount="NaN"), dict(tax_amount="bad")):
            rejected=self.mobile.post(path+"/confirm",headers=headers,json={**body, **change})
            self.assertEqual(rejected.status_code,400,rejected.json)
        self.assertIn("未税金额加税额", self.mobile.post(path+"/confirm",headers=headers,
            json={**body, "total_amount":"107"}).json["error"])
        saved=self.mobile.post(path+"/confirm",headers=headers,json={**body,"amount":""})
        self.assertEqual(saved.status_code,200,saved.json)
        self.assertEqual(saved.json["invoice"]["amount"],100)
        self.assertEqual(saved.json["invoice"]["tax_amount"],6)
