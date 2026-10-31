import unittest
from unittest.mock import patch

from flask import Flask

import models  # noqa: F401  (registers tables for create_all)
from admin import routes as admin_routes
from extensions import db


class AdminUsersRenderTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SECRET_KEY="test-secret-key-0123456789abcdef",
        )
        db.init_app(self.app)
        with self.app.app_context():
            db.create_all()

    def test_explicit_page_is_not_forwarded_to_render_template_twice(self):
        user = type("User", (), {"email": "member@example.test"})()
        with self.app.test_request_context("/admin/users?page=3"):
            with patch.object(admin_routes, "render_template", return_value="page") as render:
                rendered = admin_routes._render_users(
                    page=2, reset_token="signed-code", reset_user=user, reset_ttl=60
                )
        self.assertEqual(rendered, "page")
        self.assertEqual(render.call_args.kwargs["page"], 2)
        self.assertEqual(render.call_args.kwargs["reset_token"], "signed-code")
        self.assertEqual(render.call_args.kwargs["reset_ttl"], 60)
