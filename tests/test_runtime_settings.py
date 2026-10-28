"""Focused regression tests for runtime settings and China time behavior."""
from __future__ import annotations

import logging
import os
import unittest
from datetime import datetime, timezone

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["FLASK_ENV"] = "development"
os.environ["VERCEL"] = "1"
os.environ["ADMIN_EMAIL"] = "admin@test.com"
os.environ["ADMIN_PASSWORD"] = "Admin123456"
os.environ["SECRET_KEY"] = "runtime-settings-test-secret"

from app import ChinaTimeFormatter, create_app  # noqa: E402
from extensions import db  # noqa: E402
from models import Tool, UsageLog, User, UserToolGrant, utcnow  # noqa: E402
from utils.settings import apply_runtime_settings  # noqa: E402


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = self.app.test_client()
        response = self.client.post(
            "/login",
            data={"email": "admin@test.com", "password": "Admin123456"},
        )
        self.assertEqual(response.status_code, 302)

    def test_site_and_limits_update_frontend_and_worker_config(self) -> None:
        response = self.client.post(
            "/admin/settings",
            data={
                "site_name": "中国时间工具箱",
                "site_tagline": "设置保存后立即生效",
                "daily_free_limit": "18",
                "anon_free_limit": "6",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.app.config["SITE_NAME"], "中国时间工具箱")
        self.assertEqual(self.app.config["DAILY_FREE_LIMIT"], 18)
        self.assertEqual(self.app.config["ANON_FREE_LIMIT"], 6)

        homepage = self.client.get("/")
        self.assertIn("中国时间工具箱".encode(), homepage.data)
        self.assertIn("设置保存后立即生效".encode(), homepage.data)

        # Simulate another worker refreshing its stale process-local config.
        self.app.config.update(
            SITE_NAME="旧名称",
            DAILY_FREE_LIMIT=1,
            ANON_FREE_LIMIT=1,
        )
        with self.app.app_context():
            apply_runtime_settings(self.app, force=True)
        self.assertEqual(self.app.config["SITE_NAME"], "中国时间工具箱")
        self.assertEqual(self.app.config["DAILY_FREE_LIMIT"], 18)

    def test_admin_and_timestamp_tool_use_china_time(self) -> None:
        with self.app.app_context():
            admin = db.session.query(User).filter_by(email="admin@test.com").one()
            admin.created_at = datetime(2024, 1, 1, 0, 0, 0)
            db.session.commit()

        users_page = self.client.get("/admin/users")
        self.assertIn(b"2024-01-01 08:00", users_page.data)

        response = self.client.post(
            "/tools/timestamp/process",
            data={"direction": "ts2dt", "value": "1700000000"},
        )
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            payload["result"]["china"],
            "2023-11-15 06:13:20 UTC+08:00",
        )

        response = self.client.post(
            "/tools/timestamp/process",
            data={"direction": "dt2ts", "value": "2024-01-01 08:00:00"},
        )
        self.assertEqual(response.get_json()["result"]["seconds"], 1704067200)

    def test_usage_logs_store_utc_and_render_exact_china_time(self) -> None:
        before = datetime.now(timezone.utc).replace(tzinfo=None)
        generated = utcnow()
        after = datetime.now(timezone.utc).replace(tzinfo=None)
        self.assertIsNone(generated.tzinfo)
        self.assertLessEqual(before, generated)
        self.assertLessEqual(generated, after)

        with self.app.app_context():
            db.session.add(
                UsageLog(
                    ts=datetime(2024, 1, 1, 0, 15, 30),
                    tool_id="timestamp-regression",
                    status="success",
                )
            )
            db.session.commit()

        response = self.client.get("/admin/logs?tool=timestamp-regression")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"2024-01-01 08:15:30", response.data)
        self.assertIn("中国标准时间，UTC+8".encode(), response.data)

    def test_process_log_formatter_uses_explicit_china_offset(self) -> None:
        formatter = ChinaTimeFormatter(datefmt="%Y-%m-%d %H:%M:%S%z")
        record = logging.LogRecord(
            "timezone-test", logging.INFO, __file__, 1, "ok", (), None
        )
        record.created = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
        self.assertEqual(
            formatter.formatTime(record, formatter.datefmt),
            "2024-01-01 08:00:00+0800",
        )

    def test_private_tools_require_per_user_admin_grant(self) -> None:
        self.app.config["ENFORCE_PRIVATE_TOOL_ACCESS_IN_TESTS"] = True
        private_ids = ("fcst_merge", "reimbursement")

        self.client.get("/logout")
        self.assertEqual(self.client.get("/tools/json-formatter/").status_code, 200)
        for tool_id, route in (
            ("fcst_merge", "/tools/fcst-merge/"),
            ("reimbursement", "/tools/reimbursement/"),
        ):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 302, tool_id)
            api_response = self.client.post(route + "api/probe")
            self.assertEqual(api_response.status_code, 403, tool_id)

        with self.app.app_context():
            user = User(
                email="private-user@test.com",
                is_admin=False,
                is_active_user=True,
            )
            user.set_password("User123456")
            db.session.add(user)
            for tool_id in private_ids:
                db.session.get(Tool, tool_id).enabled = True
            db.session.commit()
            user_id = user.id

        self.client.post(
            "/login",
            data={"email": "private-user@test.com", "password": "User123456"},
        )
        homepage = self.client.get("/")
        self.assertNotIn(b'href="/tools/fcst-merge"', homepage.data)
        self.assertNotIn(b'href="/tools/reimbursement"', homepage.data)
        self.assertEqual(self.client.get("/tools/fcst-merge/").status_code, 403)
        self.client.get("/logout")

        self.client.post(
            "/login",
            data={"email": "admin@test.com", "password": "Admin123456"},
        )
        for tool_id in private_ids:
            response = self.client.post(
                f"/admin/users/{user_id}/tools/{tool_id}/toggle-access",
            )
            self.assertEqual(response.status_code, 302)
        users_page = self.client.get("/admin/users")
        self.assertIn("专有工具权限".encode(), users_page.data)
        self.assertIn("FCST 预测合并".encode(), users_page.data)
        self.assertIn("报销助手".encode(), users_page.data)

        with self.app.app_context():
            grants = db.session.query(UserToolGrant).filter_by(user_id=user_id).all()
            self.assertEqual({grant.tool_id for grant in grants}, set(private_ids))

        self.client.get("/logout")
        self.client.post(
            "/login",
            data={"email": "private-user@test.com", "password": "User123456"},
        )
        homepage = self.client.get("/")
        self.assertIn(b'href="/tools/fcst-merge"', homepage.data)
        self.assertIn(b'href="/tools/reimbursement"', homepage.data)
        # A missing optional dependency may leave the route itself unregistered
        # in this focused environment, but the access guard must no longer deny it.
        self.assertNotEqual(self.client.get("/tools/fcst-merge/").status_code, 403)
        self.assertNotEqual(self.client.get("/tools/reimbursement/").status_code, 403)

        # Revoking one grant removes it from the homepage and blocks direct access.
        self.client.get("/logout")
        self.client.post(
            "/login",
            data={"email": "admin@test.com", "password": "Admin123456"},
        )
        self.client.post(
            f"/admin/users/{user_id}/tools/fcst_merge/toggle-access",
        )
        self.client.get("/logout")
        self.client.post(
            "/login",
            data={"email": "private-user@test.com", "password": "User123456"},
        )
        homepage = self.client.get("/")
        self.assertNotIn(b'href="/tools/fcst-merge"', homepage.data)
        self.assertIn(b'href="/tools/reimbursement"', homepage.data)
        self.assertEqual(self.client.get("/tools/fcst-merge/").status_code, 403)


if __name__ == "__main__":
    unittest.main()
