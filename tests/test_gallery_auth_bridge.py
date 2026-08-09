from __future__ import annotations

import unittest

from flask import Flask
from flask_login import UserMixin

from auth.routes import auth_bp
from auth.routes import _safe_next_url
from extensions import login_manager


BRIDGE_SECRET = "gallery-introspection-test-secret-123456789"


class _TestUser(UserMixin):
    def __init__(self, user_id: int, is_admin: bool = False, email: str = "admin@example.com") -> None:
        self.id = user_id
        self.is_admin = is_admin
        self.email = email


class GalleryAuthBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        app = Flask(__name__)
        app.config.update(
            SECRET_KEY="gallery-bridge-session-test",
            TESTING=True,
            GALLERY_INTROSPECTION_SECRET=BRIDGE_SECRET,
        )
        login_manager.init_app(app)
        login_manager.user_loader(lambda user_id: _TestUser(int(user_id), int(user_id) == 1))
        app.register_blueprint(auth_bp)
        self.client = app.test_client()

    def test_bridge_fails_closed_without_server_secret(self):
        response = self.client.get("/internal/gallery/session")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_bridge_returns_guest_without_exposing_session_fields(self):
        response = self.client.get(
            "/internal/gallery/session",
            headers={"X-Mavis-Introspection-Secret": BRIDGE_SECRET},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"role": "guest"})
        self.assertEqual(response.headers["Vary"], "Cookie")

    def test_bridge_compat_alias_returns_guest(self):
        response = self.client.get(
            "/auth/internal/gallery/session",
            headers={"X-Mavis-Introspection-Secret": BRIDGE_SECRET},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"role": "guest"})

    def test_bridge_maps_authenticated_admin_to_minimal_context(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = "1"
            session["_fresh"] = True
        response = self.client.get(
            "/internal/gallery/session",
            headers={"X-Mavis-Introspection-Secret": BRIDGE_SECRET},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"role": "admin", "userId": 1, "email": "admin@example.com"},
        )

    def test_bridge_includes_email_for_authenticated_user(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = "2"
            session["_fresh"] = True
        response = self.client.get(
            "/internal/gallery/session",
            headers={"X-Mavis-Introspection-Secret": BRIDGE_SECRET},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"role": "user", "userId": 2, "email": "admin@example.com"},
        )

    def test_gallery_return_url_allows_only_configured_https_origin(self):
        gallery = "https://gallery.example.com/create"
        self.assertEqual(
            _safe_next_url("https://gallery.example.com/my-images?cursor=1", gallery),
            "https://gallery.example.com/my-images?cursor=1",
        )
        self.assertEqual(
            _safe_next_url("https://gallery.example.com:443/my-images", gallery),
            "https://gallery.example.com:443/my-images",
        )
        self.assertEqual(_safe_next_url("/billing", gallery), "/billing")
        self.assertIsNone(_safe_next_url("//evil.example/steal", gallery))
        self.assertIsNone(_safe_next_url("https://evil.example/steal", gallery))
        self.assertIsNone(_safe_next_url("http://gallery.example.com/steal", gallery))
        self.assertIsNone(_safe_next_url("https://gallery.example.com:8443/steal", gallery))
        self.assertIsNone(_safe_next_url("https://user:pass@gallery.example.com/steal", gallery))
        self.assertIsNone(_safe_next_url("https://gallery.example.com./steal", gallery))

    def test_gallery_return_url_allows_same_origin_loopback_http_for_local_development(self):
        gallery = "http://127.0.0.1:3000/create"
        self.assertEqual(
            _safe_next_url("http://127.0.0.1:3000/tasks", gallery),
            "http://127.0.0.1:3000/tasks",
        )
        self.assertIsNone(_safe_next_url("http://127.0.0.1:3001/tasks", gallery))
        self.assertIsNone(_safe_next_url("http://localhost:3000/tasks", gallery))
        self.assertIsNone(_safe_next_url("http://evil.example:3000/tasks", gallery))

    def test_gallery_return_url_rejects_header_and_path_smuggling(self):
        gallery = "https://gallery.example.com/create"
        for value in ("/\nevil.example/steal", "/\revil.example/steal", "/\\evil.example/steal", "/ evil.example/steal"):
            self.assertIsNone(_safe_next_url(value, gallery), value)


if __name__ == "__main__":
    unittest.main()
