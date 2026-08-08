"""Regression: users with custom_limits set must still be able to log in.

custom_limit_map used to return None whenever custom_limits was non-empty,
which made remaining_for() crash while rendering the home page right after
login (AttributeError: 'NoneType' object has no attribute 'get').
"""
from __future__ import annotations

import os
import unittest

os.environ["FLASK_ENV"] = "production"
os.environ["DATABASE_URL"] = "sqlite://"  # in-memory; never touch instance/app.db

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Tool, User  # noqa: E402


class UserCustomLimitsTest(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        with app.app_context():
            # Other discovery-ordered modules may share/tear down the in-memory
            # schema, so make this test self-contained: ensure tables exist and
            # at least one internal tool is present so the home page exercises
            # remaining_for() (the code path that used to crash on login).
            db.create_all()
            if db.session.get(Tool, "test-login-tool") is None:
                db.session.add(
                    Tool(
                        id="test-login-tool",
                        name="Login Test Tool",
                        description="regression",
                        icon="bi-tools",
                        color="#0d6efd",
                        route="/tools/json-formatter",
                        blueprint_module="tools.json_formatter",
                        external_url="",
                        enabled=True,
                        required_plan="free",
                        category="other",
                        order=100,
                    )
                )
            db.session.commit()
        self.client = app.test_client()

    def _create_user(self, custom_limits: str | None, email: str = "member@test.com") -> int:
        with app.app_context():
            user = User(
                email=email,
                is_admin=False,
                is_active_user=True,
                custom_limits=custom_limits,
            )
            user.set_password("Passw0rd1")
            db.session.add(user)
            db.session.commit()
            return user.id

    def test_custom_limit_map_parses_non_empty_json(self) -> None:
        with app.app_context():
            user = db.session.get(
                User, self._create_user('{"json_formatter": 50}', "parse@test.com")
            )
            self.assertIsNotNone(user)
            assert user is not None
            self.assertEqual(user.custom_limit_map, {"json_formatter": 50})
            self.assertEqual(user.limit_for("json_formatter", 10), 50)
            self.assertEqual(user.limit_for("pdf_merge", 10), 10)

    def test_custom_limit_map_handles_empty_and_invalid_json(self) -> None:
        with app.app_context():
            for email, raw in (
                ("empty@test.com", None),
                ("brace@test.com", "{}"),
                ("bad@test.com", "not-json"),
            ):
                user = db.session.get(User, self._create_user(raw, email))
                self.assertIsNotNone(user)
                assert user is not None
                self.assertEqual(user.custom_limit_map, {})

    def test_member_with_custom_limit_can_log_in_and_render_home(self) -> None:
        self._create_user('{"json_formatter": 50}', "login-member@test.com")
        response = self.client.post(
            "/login",
            data={"email": "login-member@test.com", "password": "Passw0rd1", "remember": "y"},
            follow_redirects=False,
        )
        self.assertIn(response.status_code, (301, 302))
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("今日剩余", home.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
