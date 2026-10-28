from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unittest
from unittest import mock

from flask import Flask

from utils.gallery_admin_client import (
    GalleryAdminError,
    gallery_admin_dashboard,
    gallery_delete_image,
    sign_admin_context,
)


SECRET = "gallery-internal-hmac-test-secret-123456"


def _app(**overrides) -> Flask:
    app = Flask(__name__)
    app.config.update(
        GALLERY_SERVICE_BASE_URL="https://api.example.com",
        GALLERY_INTERNAL_HMAC_SECRET=SECRET,
    )
    app.config.update(overrides)
    return app


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object | None = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class GalleryAdminClientTests(unittest.TestCase):
    def test_sign_admin_context_matches_bff_contract(self):
        context, signature = sign_admin_context(user_id=7, secret=SECRET, now=1_700_000_000)
        payload = json.loads(base64.urlsafe_b64decode(context + "==").decode("utf-8"))
        self.assertEqual(payload["v"], 1)
        self.assertEqual(payload["role"], "admin")
        self.assertEqual(payload["userId"], 7)
        self.assertEqual(payload["issuedAt"], 1_700_000_000)
        self.assertEqual(payload["expiresAt"], 1_700_000_060)
        self.assertRegex(payload["requestId"], r"^[0-9a-f]{8}-[0-9a-f-]{27}$")
        expected = base64.urlsafe_b64encode(
            hmac.new(SECRET.encode(), context.encode(), hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        self.assertEqual(signature, expected)

    def test_unconfigured_secret_raises_without_leaking_value(self):
        app = _app(GALLERY_INTERNAL_HMAC_SECRET="short")
        with app.app_context():
            with self.assertRaises(GalleryAdminError) as ctx:
                gallery_admin_dashboard(1)
        self.assertEqual(ctx.exception.code, "unconfigured")
        self.assertNotIn("short", ctx.exception.message)

    def test_http_non_loopback_base_url_is_rejected(self):
        app = _app(GALLERY_SERVICE_BASE_URL="http://api.example.com")
        with app.app_context():
            with self.assertRaises(GalleryAdminError) as ctx:
                gallery_admin_dashboard(1)
        self.assertEqual(ctx.exception.code, "unconfigured")

    def test_dashboard_sends_signed_headers(self):
        app = _app()
        payload = {"overview": {"pendingModeration": 1}}
        with app.app_context(), mock.patch("requests.request", return_value=FakeResponse(200, payload)) as request:
            result = gallery_admin_dashboard(7)
        self.assertEqual(result, payload)
        call = request.call_args
        self.assertEqual(call.args[0], "GET")
        self.assertEqual(call.args[1], "https://api.example.com/v1/admin/dashboard")
        headers = call.kwargs["headers"]
        self.assertIn("X-Mavis-User-Context", headers)
        self.assertIn("X-Mavis-User-Signature", headers)
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(call.kwargs["timeout"], 8)

    def test_error_response_is_mapped_safely(self):
        app = _app()
        response = FakeResponse(409, {"error": {"code": "conflict", "message": "stale"}})
        with app.app_context(), mock.patch("requests.request", return_value=response):
            with self.assertRaises(GalleryAdminError) as ctx:
                gallery_admin_dashboard(7)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "conflict")
        self.assertEqual(ctx.exception.message, "stale")

    def test_delete_204_returns_none(self):
        app = _app()
        with app.app_context(), mock.patch("requests.request", return_value=FakeResponse(204)) as request:
            result = gallery_delete_image(7, "123e4567-e89b-42d3-a456-426614174000")
        self.assertIsNone(result)
        self.assertEqual(request.call_args.args[1], "https://api.example.com/v1/images/123e4567-e89b-42d3-a456-426614174000")

    def test_timeout_is_reported_as_service_unavailable(self):
        app = _app()
        with app.app_context(), mock.patch("requests.request", side_effect=__import__("requests").Timeout()):
            with self.assertRaises(GalleryAdminError) as ctx:
                gallery_admin_dashboard(7)
        self.assertEqual(ctx.exception.code, "service_unavailable")


if __name__ == "__main__":
    unittest.main()
