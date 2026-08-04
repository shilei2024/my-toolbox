"""Full round-trip contract tests for the Flask to Gallery login bridge.

Covers the production story: main-site entry -> Gallery login/register -> safe
return to Gallery -> signed session introspection -> logout. Also verifies the
configuration preflight CLI and the fail-closed introspection endpoint without
ever printing secret values.
"""
from __future__ import annotations

import os
import unittest
from urllib.parse import quote

# Must be set before importing the app factory so Config picks them up.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["FLASK_ENV"] = "development"
os.environ["VERCEL"] = "1"  # skip APScheduler in tests
os.environ["ADMIN_EMAIL"] = "admin@test.com"
os.environ["ADMIN_PASSWORD"] = "Admin123456"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"
os.environ["AI_IMAGE_EXTERNAL_URL"] = "https://gallery.example.com/create"
os.environ["GALLERY_INTROSPECTION_SECRET"] = "gallery-introspection-test-secret-123456789"

from app import create_app  # noqa: E402


GALLERY = "https://gallery.example.com/create"
SECRET = "gallery-introspection-test-secret-123456789"
REGISTER = {"email": "", "password": "Passw0rd1", "confirm": "Passw0rd1", "remember": "y"}


class GalleryRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_app()
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.app.config["TESTING"] = True
        cls.app.config["AI_IMAGE_EXTERNAL_URL"] = GALLERY
        cls.app.config["GALLERY_INTROSPECTION_SECRET"] = SECRET
        cls.app.config["APP_BASE_URL"] = "https://tools.example.com"
        cls.app.config["SESSION_COOKIE_DOMAIN"] = ".example.com"
        cls.app.config["SESSION_COOKIE_SECURE"] = True

    def _register(self, email: str, next_url: str = GALLERY) -> "object":
        data = dict(REGISTER, email=email)
        return self.app.test_client().post(
            f"/register?next={quote(next_url, safe='')}",
            data=data,
            follow_redirects=False,
        )

    def test_register_returns_to_gallery_then_introspection_identifies_user(self):
        client = self.app.test_client()
        response = client.post(
            f"/register?next={quote(GALLERY, safe='')}",
            data=dict(REGISTER, email="roundtrip@example.com"),
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], GALLERY)

        introspection = client.get(
            "/internal/gallery/session",
            headers={"X-Mavis-Introspection-Secret": SECRET},
        )
        self.assertEqual(introspection.status_code, 200)
        payload = introspection.get_json()
        self.assertEqual(payload["role"], "user")
        self.assertIsInstance(payload["userId"], int)

    def test_login_and_logout_round_trip_keep_gallery_return(self):
        client = self.app.test_client()
        self._register("roundtrip-login@example.com")
        client.get("/logout", follow_redirects=False)

        response = client.post(
            f"/login?next={quote(GALLERY, safe='')}",
            data={"email": "roundtrip-login@example.com", "password": "Passw0rd1", "remember": "y"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], GALLERY)

        logout = client.get(
            f"/logout?next={quote('https://gallery.example.com/my-images', safe='')}",
            follow_redirects=False,
        )
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(logout.headers["Location"], "https://gallery.example.com/my-images")

    def test_malicious_next_falls_back_to_home(self):
        response = self._register("roundtrip-evil@example.com", next_url="https://evil.example/steal")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_introspection_fails_closed_without_exposing_session(self):
        for headers in ({}, {"X-Mavis-Introspection-Secret": "wrong-secret"}):
            response = self.app.test_client().get("/internal/gallery/session", headers=headers)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            body = response.get_data(as_text=True)
            self.assertNotIn("role", body)
            self.assertNotIn("userId", body)

    def test_preflight_cli_passes_with_complete_config_without_leaking_secret(self):
        result = self.app.test_cli_runner().invoke(args=["check-gallery-integration"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("[PASS]", result.output)
        self.assertNotIn(SECRET, result.output)

    def test_preflight_cli_fails_and_never_prints_secret_values(self):
        original = self.app.config["AI_IMAGE_EXTERNAL_URL"]
        try:
            self.app.config["AI_IMAGE_EXTERNAL_URL"] = ""
            result = self.app.test_cli_runner().invoke(args=["check-gallery-integration"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("[FAIL]", result.output)
            self.assertNotIn(SECRET, result.output)
        finally:
            self.app.config["AI_IMAGE_EXTERNAL_URL"] = original


if __name__ == "__main__":
    unittest.main()
