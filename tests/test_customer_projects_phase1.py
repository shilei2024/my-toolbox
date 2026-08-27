"""Phase 1 customer-project domain, permission, API and page regression tests."""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ["FLASK_ENV"] = "production"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "phase-1-test-secret-key-that-is-long-enough"
os.environ["ADMIN_EMAIL"] = "bootstrap@test.com"
os.environ["ADMIN_PASSWORD"] = "SafeBootstrapPassword123!"

from app import app  # noqa: E402
from customer_projects.models import (  # noqa: E402
    CustomerProject,
    MaterialCompetitor,
    ProjectActivity,
    ProjectMaterial,
    ProjectStageEvent,
)
from customer_projects.services.projects import (  # noqa: E402
    bootstrap_organization,
    create_customer,
    create_project,
)
from extensions import db  # noqa: E402
from models import User  # noqa: E402
from shared.models import Organization, OrganizationMembership  # noqa: E402


class CustomerProjectsPhase1Test(unittest.TestCase):
    def setUp(self) -> None:
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            CUSTOMER_PROJECTS_ENABLED=True,
            CUSTOMER_PROJECTS_PILOT_EMAILS="",
        )
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.admin_id = self._add_user("manager@test.com", admin=True)
            self.sales_id = self._add_user("sales@test.com")
            self.other_id = self._add_user("other@test.com")
            org = bootstrap_organization("测试组织", self.admin_id)
            self.org_id = org.id
            sales_membership = OrganizationMembership(
                organization_id=org.id, user_id=self.sales_id
            )
            sales_membership.set_roles(["sales"])
            db.session.add(sales_membership)
            other_membership = OrganizationMembership(
                organization_id=org.id, user_id=self.other_id
            )
            other_membership.set_roles(["sales"])
            db.session.add(other_membership)
            db.session.commit()
        self.client = app.test_client()

    def _add_user(self, email: str, admin: bool = False) -> int:
        user = User(email=email, is_admin=admin, is_active_user=True)
        user.set_password("Passw0rd1")
        db.session.add(user)
        db.session.flush()
        return user.id

    def _login(self, email: str = "sales@test.com") -> None:
        response = self.client.post(
            "/login", data={"email": email, "password": "Passw0rd1"}
        )
        self.assertIn(response.status_code, (301, 302))

    def _seed_project(self) -> str:
        with app.app_context():
            membership = db.session.scalar(
                db.select(OrganizationMembership).where(
                    OrganizationMembership.user_id == self.sales_id
                )
            )
            customer = create_customer({"name": "示例电子"}, membership)
            db.session.flush()
            project = create_project(
                {
                    "customer_id": customer.id,
                    "name": "车载控制器",
                    "stage_code": "evaluation",
                    "primary_sales_user_id": self.sales_id,
                    "next_action": "确认样品数量",
                    "next_follow_up_at": (
                        datetime.now(timezone.utc) + timedelta(days=2)
                    ).isoformat(),
                    "assessment_grade": "B",
                    "probability_band": 30,
                },
                membership,
                "seed-project",
            )
            db.session.commit()
            return project.id

    def test_feature_flag_hides_module_and_navigation(self) -> None:
        self._login()
        app.config["CUSTOMER_PROJECTS_ENABLED"] = False
        self.assertEqual(self.client.get("/customer-projects/").status_code, 404)
        home = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("客户项目</a>", home)

    def test_project_create_is_idempotent_and_scoped(self) -> None:
        project_id = self._seed_project()
        self._login()
        listing = self.client.get("/api/v1/customer-projects/projects")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()["data"][0]["id"], project_id)
        detail = self.client.get(f"/api/v1/customer-projects/projects/{project_id}")
        self.assertEqual(detail.headers["ETag"], '"1"')
        with app.app_context():
            self.assertEqual(db.session.query(CustomerProject).count(), 1)
            self.assertEqual(db.session.query(ProjectStageEvent).count(), 1)

    def test_optimistic_lock_returns_409_without_overwrite(self) -> None:
        project_id = self._seed_project()
        self._login()
        first = self.client.patch(
            f"/api/v1/customer-projects/projects/{project_id}",
            json={"next_action": "准备 20 片样品"},
            headers={"If-Match": '"1"'},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["ETag"], '"2"')
        stale = self.client.patch(
            f"/api/v1/customer-projects/projects/{project_id}",
            json={"next_action": "覆盖他人内容"},
            headers={"If-Match": '"1"'},
        )
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.get_json()["error"]["code"], "PROJECT_VERSION_CONFLICT")
        with app.app_context():
            self.assertEqual(db.session.get(CustomerProject, project_id).next_action, "准备 20 片样品")

    def test_activity_updates_snapshot_and_is_idempotent(self) -> None:
        project_id = self._seed_project()
        self._login()
        payload = {
            "activity_type": "meeting",
            "summary": "确认送样计划",
            "next_action": "安排寄送",
            "next_follow_up_at": (datetime.now(timezone.utc) + timedelta(days=4)).isoformat(),
            "project_version": 1,
            "is_meaningful": True,
        }
        first = self.client.post(
            f"/api/v1/customer-projects/projects/{project_id}/activities",
            json=payload,
            headers={"Idempotency-Key": "activity-one"},
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            f"/api/v1/customer-projects/projects/{project_id}/activities",
            json=payload,
            headers={"Idempotency-Key": "activity-one"},
        )
        self.assertEqual(second.status_code, 201)
        with app.app_context():
            self.assertEqual(db.session.query(ProjectActivity).count(), 1)
            project = db.session.get(CustomerProject, project_id)
            self.assertEqual(project.version, 2)
            self.assertEqual(project.next_action, "安排寄送")

    def test_non_member_project_is_not_disclosed(self) -> None:
        project_id = self._seed_project()
        self._login("other@test.com")
        response = self.client.get(f"/api/v1/customer-projects/projects/{project_id}")
        self.assertEqual(response.status_code, 404)

    def test_materials_allow_zero_or_multiple_competitors(self) -> None:
        project_id = self._seed_project()
        self._login()
        first = self.client.post(
            f"/api/v1/customer-projects/projects/{project_id}/materials",
            json={"promoted_brand": "Mavis", "promoted_mpn": "MPX-8100", "category_code": "Power IC"},
            headers={"Idempotency-Key": "material-one"},
        )
        self.assertEqual(first.status_code, 201)
        material_id = first.get_json()["data"]["id"]
        material_retry = self.client.post(
            f"/api/v1/customer-projects/projects/{project_id}/materials",
            json={"promoted_brand": "Mavis", "promoted_mpn": "MPX-8100", "category_code": "Power IC"},
            headers={"Idempotency-Key": "material-one"},
        )
        self.assertEqual(material_retry.status_code, 201)
        self.assertEqual(material_retry.get_json()["data"]["id"], material_id)
        pending_payload = {"brand": "竞品品牌", "model_pending": True}
        pending = self.client.post(
            f"/api/v1/customer-projects/materials/{material_id}/competitors",
            json=pending_payload,
            headers={"Idempotency-Key": "competitor-one"},
        )
        self.assertEqual(pending.status_code, 201)
        competitor_retry = self.client.post(
            f"/api/v1/customer-projects/materials/{material_id}/competitors",
            json=pending_payload,
            headers={"Idempotency-Key": "competitor-one"},
        )
        self.assertEqual(competitor_retry.status_code, 201)
        self.assertEqual(competitor_retry.get_json()["data"]["id"], pending.get_json()["data"]["id"])
        second = self.client.post(
            f"/api/v1/customer-projects/materials/{material_id}/competitors",
            json={"brand": "另一品牌", "mpn": "ALT-100"},
            headers={"Idempotency-Key": "competitor-two"},
        )
        self.assertEqual(second.status_code, 201)
        with app.app_context():
            self.assertEqual(db.session.query(ProjectMaterial).count(), 1)
            self.assertEqual(db.session.query(MaterialCompetitor).count(), 2)

    def test_stage_history_soft_delete_and_manager_restore(self) -> None:
        project_id = self._seed_project()
        self._login()
        transition = self.client.post(
            f"/api/v1/customer-projects/projects/{project_id}/stage-transitions",
            json={"to_stage_code": "initiated", "reason": "客户确认立项", "project_version": 1},
            headers={"Idempotency-Key": "stage-one"},
        )
        self.assertEqual(transition.status_code, 201)
        self.assertEqual(transition.get_json()["data"]["from_stage_code"], "evaluation")
        deleted = self.client.delete(
            f"/api/v1/customer-projects/projects/{project_id}",
            json={"reason": "测试软删除"},
            headers={"If-Match": '"2"'},
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/v1/customer-projects/projects/{project_id}").status_code, 404)
        self.client.post("/logout")
        self._login("manager@test.com")
        restored = self.client.post(
            f"/api/v1/customer-projects/trash/projects/{project_id}/restore"
        )
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.get_json()["data"]["version"], 4)

    def test_dashboard_and_detail_render_responsive_product_pages(self) -> None:
        project_id = self._seed_project()
        self._login()
        dashboard = self.client.get("/customer-projects/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("今天先推进什么", dashboard.get_data(as_text=True))
        detail = self.client.get(f"/customer-projects/projects/{project_id}")
        self.assertEqual(detail.status_code, 200)
        html = detail.get_data(as_text=True)
        self.assertIn("新增跟进", html)
        self.assertIn("尚未添加推广物料", html)


if __name__ == "__main__":
    unittest.main()
