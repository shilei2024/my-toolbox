from __future__ import annotations

import unittest

from flask import Flask
from flask_login import UserMixin

from auth.routes import auth_bp
from extensions import login_manager


BRIDGE_SECRET = "gallery-introspection-test-secret-123456789"


class _TestUser(UserMixin):
    def __init__(self, user_id: int, is_admin: bool = False) -> None:
        self.id = user_id
        self.is_admin = is_admin


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
        self.assertEqual(response.get_json(), {"role": "admin", "userId": 1})


if __name__ == "__main__":
    unittest.main()
