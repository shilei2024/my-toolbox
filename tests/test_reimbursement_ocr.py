"""Reimbursement OCR fallbacks and public-safe failure messages."""
from __future__ import annotations

import unittest
from unittest import mock

from flask import Flask

from tools.reimbursement import _baidu_ocr_from_bytes, _parse_general


class ReimbursementOcrTest(unittest.TestCase):
    def test_baidu_vat_template_mismatch_falls_back_to_general_ocr(self) -> None:
        app = Flask(__name__)
        words = [
            {"words": "铁路电子客票"},
            {"words": "发票号码：12345678901234567890"},
            {"words": "2026年09月06日"},
            {"words": "深圳北 至 上海虹桥"},
            {"words": "票价 ¥ 680.50"},
            {"words": "仅供报销使用"},
        ]
        with app.app_context(), mock.patch(
            "tools.reimbursement.requests.get",
            return_value=_FakeResponse({"access_token": "token"}),
        ), mock.patch(
            "tools.reimbursement._preprocess_for_ocr", return_value=[b"image"]
        ), mock.patch(
            "tools.reimbursement._baidu_vat_call",
            side_effect=RuntimeError(
                "Baidu VAT error 282103: recognize error, failed to match the template"
            ),
        ), mock.patch(
            "tools.reimbursement._baidu_gen_call", return_value=words
        ) as general_call:
            result = _baidu_ocr_from_bytes(b"image", "api-key", "secret")

        self.assertEqual(result["invoice_number"], "12345678901234567890")
        self.assertEqual(result["invoice_date"], "2026-09-06")
        self.assertEqual(result["seller_name"], "中国铁路")
        self.assertEqual(result["total_amount"], "680.50")
        self.assertEqual(result["description"], "火车票")
        general_call.assert_called_once()

    def test_general_ocr_parses_legacy_train_ticket_fields(self) -> None:
        result = _parse_general(
            [
                {"words": "限乘当日当次车"},
                {"words": "车票号：17C060124"},
                {"words": "2026年9月6日 10:33开"},
                {"words": "票价：￥134.50"},
            ]
        )

        self.assertEqual(result["invoice_number"], "17C060124")
        self.assertEqual(result["invoice_date"], "2026-09-06")
        self.assertEqual(result["seller_name"], "中国铁路")
        self.assertEqual(result["total_amount"], "134.50")
        self.assertEqual(result["description"], "火车票")


class _FakeResponse:
    status_code = 200

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


if __name__ == "__main__":
    unittest.main()
