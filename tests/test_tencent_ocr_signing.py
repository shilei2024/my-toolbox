"""Tencent Cloud OCR adapter: TC3 signing shape and VAT invoice mapping."""
from __future__ import annotations

import re
import unittest
from unittest import mock

from tools.reimbursement import _tc3_authorization, _tencent_ocr_from_bytes


class FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self) -> dict:
        return self._payload


class TencentOcrTest(unittest.TestCase):
    def test_tc3_authorization_is_deterministic_and_well_formed(self) -> None:
        args = {
            "secret_id": "AKIDtest",
            "secret_key": "secret-key",
            "service": "ocr",
            "host": "ocr.tencentcloudapi.com",
            "action": "VatInvoiceOCR",
            "version": "2018-11-19",
            "region": "ap-shanghai",
            "payload": '{"ImageBase64":"aGVsbG8="}',
            "timestamp": 1551113065,
        }
        first = _tc3_authorization(**args)
        second = _tc3_authorization(**args)
        self.assertEqual(first, second)
        self.assertIn("TC3-HMAC-SHA256 Credential=AKIDtest/2019-02-25/ocr/tc3_request", first)
        self.assertIn("SignedHeaders=content-type;host", first)
        self.assertRegex(first, r"Signature=[0-9a-f]{64}$")

    def test_vat_invoice_response_is_mapped_to_platform_fields(self) -> None:
        payload = {
            "Response": {
                "VatInvoiceInfos": [
                    {"Name": "发票号码", "Value": "12345678"},
                    {"Name": "开票日期", "Value": "2026-08-07"},
                    {"Name": "销售方名称", "Value": "腾讯科技"},
                    {"Name": "金额", "Value": "90.00"},
                    {"Name": "税额", "Value": "10.00"},
                    {"Name": "价税合计(小写)", "Value": "100.00"},
                    {"Name": "货物或应税劳务名称", "Value": "云服务"},
                ]
            }
        }
        with mock.patch("tools.reimbursement.requests.post", return_value=FakeResponse(payload)) as post:
            result = _tencent_ocr_from_bytes(b"fake-image-bytes", "test-id", "test-key")
        self.assertIsNotNone(result)
        self.assertEqual(result["invoice_number"], "12345678")
        self.assertEqual(result["invoice_date"], "2026-08-07")
        self.assertEqual(result["seller_name"], "腾讯科技")
        self.assertEqual(result["amount_excluding_tax"], "90.00")
        self.assertEqual(result["tax_amount"], "10.00")
        self.assertEqual(result["total_amount"], "100.00")
        self.assertEqual(result["description"], "云服务")
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(headers["X-TC-Action"], "VatInvoiceOCR")
        self.assertIn("TC3-HMAC-SHA256 Credential=", headers["Authorization"])

    def test_ocr_error_raises_without_leaking_response_body(self) -> None:
        payload = {"Response": {"Error": {"Code": "AuthFailure", "Message": "secret"}}}
        with mock.patch("tools.reimbursement.requests.post", return_value=FakeResponse(payload, status=403)):
            with self.assertRaises(RuntimeError) as ctx:
                _tencent_ocr_from_bytes(b"x", "test-id", "test-key")
        self.assertNotIn("secret", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
