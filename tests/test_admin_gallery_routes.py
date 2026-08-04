from __future__ import annotations

import os
import unittest
from unittest import mock

# Must be set before importing the app factory so Config picks them up.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["FLASK_ENV"] = "development"
os.environ["VERCEL"] = "1"
os.environ["ADMIN_EMAIL"] = "admin@test.com"
os.environ["ADMIN_PASSWORD"] = "Admin123456"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"
os.environ["GALLERY_SERVICE_BASE_URL"] = "https://api.example.com"
os.environ["GALLERY_INTERNAL_HMAC_SECRET"] = "gallery-internal-hmac-test-secret-123456"

from app import create_app  # noqa: E402
from utils.gallery_admin_client import GalleryAdminError  # noqa: E402


FAKE_DASHBOARD = {
    "overview": {
        "pendingModeration": 1,
        "publicImages": 3,
        "jobsLast24Hours": 5,
        "failedJobsLast24Hours": 0,
        "activeProviders": 1,
        "enabledWorkflows": 2,
    },
    "moderationQueue": [
        {
            "id": "123e4567-e89b-42d3-a456-426614174000",
            "slug": "test-image",
            "title": "测试作品",
            "workflowName": "portrait",
            "moderationStatus": "pending",
            "visibility": "public",
            "promptVisibility": "hidden",
            "thumbnailUrl": "https://assets.example.com/test.webp",
            "createdAt": "2026-08-05T00:00:00.000Z",
            "updatedAt": "2026-08-05T00:00:00.000Z",
        }
    ],
    "providers": [
        {
            "id": "222e4567-e89b-42d3-a456-426614174000",
            "code": "openai",
            "displayName": "OpenAI",
            "adapterType": "openai",
            "status": "active",
            "priority": 10,
            "secretConfigured": True,
            "consecutiveFailures": 0,
            "lastHealthAt": "2026-08-05T00:00:00.000Z",
            "updatedAt": "2026-08-05T00:00:00.000Z",
        }
    ],
    "workflows": [
        {
            "id": "333e4567-e89b-42d3-a456-426614174000",
            "slug": "portrait",
            "name": "人像",
            "category": "portrait",
            "isEnabled": True,
            "activeVersion": 2,
            "bindingCount": 1,
            "sortOrder": 10,
            "updatedAt": "2026-08-05T00:00:00.000Z",
        }
    ],
    "recentJobs": [
        {
            "id": "444e4567-e89b-42d3-a456-426614174000",
            "workflowName": "人像",
            "providerCode": "openai",
            "status": "completed",
            "actualCost": 0.5,
            "createdAt": "2026-08-05T00:00:00.000Z",
        }
    ],
    "recentAudit": [
        {
            "id": "555e4567-e89b-42d3-a456-426614174000",
            "actorUserId": 1,
            "action": "admin.image_moderated",
            "resourceType": "image",
            "resourceId": "123e4567-e89b-42d3-a456-426614174000",
            "createdAt": "2026-08-05T00:00:00.000Z",
        }
    ],
}


class AdminGalleryRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = create_app()
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.app.config["TESTING"] = True
        cls.admin = cls.app.test_client()
        response = cls.admin.post(
            "/login",
            data={"email": "admin@test.com", "password": "Admin123456", "remember": "y"},
            follow_redirects=False,
        )
        assert response.status_code in (301, 302)

    def test_gallery_dashboard_renders_unified_admin(self):
        with mock.patch("admin.gallery_admin.gallery_admin_dashboard", return_value=FAKE_DASHBOARD):
            response = self.admin.get("/admin/gallery")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("AI 作图管理", body)
        self.assertIn("内容审核", body)
        self.assertIn("Provider", body)
        self.assertIn("工作流", body)
        self.assertIn("测试作品", body)
        self.assertIn("审计记录", body)

    def test_gallery_dashboard_degrades_gracefully_when_unconfigured(self):
        with mock.patch(
            "admin.gallery_admin.gallery_admin_dashboard",
            side_effect=GalleryAdminError("unconfigured", "Gallery 管理后台未配置。", 503),
        ):
            response = self.admin.get("/admin/gallery")
        self.assertEqual(response.status_code, 200)
        self.assertIn("暂时无法读取 Gallery 管理数据", response.get_data(as_text=True))

    def test_moderation_post_calls_signed_client_and_redirects(self):
        with mock.patch("admin.gallery_admin.gallery_moderate_image", return_value=FAKE_DASHBOARD["moderationQueue"][0]) as moderate:
            response = self.admin.post(
                "/admin/gallery/images/123e4567-e89b-42d3-a456-426614174000/moderation",
                data={"decision": "approved", "expected_updated_at": "2026-08-05T00:00:00.000Z"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/gallery", response.headers["Location"])
        moderate.assert_called_once_with(
            1,
            "123e4567-e89b-42d3-a456-426614174000",
            "approved",
            "2026-08-05T00:00:00.000Z",
        )

    def test_provider_post_validates_and_redirects(self):
        with mock.patch("admin.gallery_admin.gallery_update_provider", return_value=FAKE_DASHBOARD["providers"][0]) as update:
            response = self.admin.post(
                "/admin/gallery/providers/222e4567-e89b-42d3-a456-426614174000",
                data={"status": "disabled", "priority": "20", "expected_updated_at": "2026-08-05T00:00:00.000Z"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        update.assert_called_once_with(1, "222e4567-e89b-42d3-a456-426614174000", "disabled", 20, "2026-08-05T00:00:00.000Z")

    def test_workflow_post_validates_and_redirects(self):
        with mock.patch("admin.gallery_admin.gallery_update_workflow", return_value=FAKE_DASHBOARD["workflows"][0]) as update:
            response = self.admin.post(
                "/admin/gallery/workflows/333e4567-e89b-42d3-a456-426614174000",
                data={"is_enabled": "on", "sort_order": "15", "expected_updated_at": "2026-08-05T00:00:00.000Z"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 302)
        update.assert_called_once_with(
            1,
            "333e4567-e89b-42d3-a456-426614174000",
            is_enabled=True,
            sort_order=15,
            expected_updated_at="2026-08-05T00:00:00.000Z",
        )

    def test_non_admin_cannot_access_gallery_admin(self):
        client = self.app.test_client()
        client.post(
            "/register",
            data={"email": "gallery-user@example.com", "password": "Passw0rd1", "confirm": "Passw0rd1", "remember": "y"},
            follow_redirects=False,
        )
        client.get("/logout", follow_redirects=False)
        client.post(
            "/login",
            data={"email": "gallery-user@example.com", "password": "Passw0rd1", "remember": "y"},
            follow_redirects=False,
        )
        response = client.get("/admin/gallery")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
