"""Phase 4 controlled Excel project import tests."""
from __future__ import annotations

import os
import unittest
from io import BytesIO

from openpyxl import Workbook

os.environ["FLASK_ENV"] = "production"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "phase-4-import-test-secret-key-that-is-long-enough"
os.environ["ADMIN_EMAIL"] = "bootstrap@test.com"
os.environ["ADMIN_PASSWORD"] = "SafeBootstrapPassword123!"

from app import app  # noqa: E402
from customer_projects.models import Customer, CustomerProject, ProjectImportBatch, ProjectImportRow  # noqa: E402
from customer_projects.services.projects import bootstrap_organization  # noqa: E402
from extensions import db  # noqa: E402
from models import User  # noqa: E402
from shared.models import OrganizationMembership  # noqa: E402


class CustomerProjectImportTest(unittest.TestCase):
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
            manager = User(email="manager@test.com", is_admin=True, is_active_user=True)
            manager.set_password("Passw0rd1")
            sales = User(email="sales@test.com", is_active_user=True)
            sales.set_password("Passw0rd1")
            db.session.add_all((manager, sales))
            db.session.flush()
            self.manager_id = manager.id
            self.sales_id = sales.id
            org = bootstrap_organization("导入测试组织", manager.id)
            self.org_id = org.id
            membership = OrganizationMembership(
                organization_id=org.id,
                user_id=sales.id,
                status="active",
            )
            membership.set_roles({"sales"})
            db.session.add(membership)
            db.session.commit()
        self.client = app.test_client()
        response = self.client.post(
            "/login", data={"email": "manager@test.com", "password": "Passw0rd1"}
        )
        self.assertIn(response.status_code, (301, 302))

    def _workbook(self, rows: list[list[object]]) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(
            [
                "客户名称",
                "项目名称",
                "产品名称",
                "项目年用量",
                "阶段",
                "主业务邮箱",
                "下一步",
                "下次跟进时间",
                "评估等级",
                "成功概率",
            ]
        )
        for row in rows:
            sheet.append(row)
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def _preview(self, content: bytes):
        return self.client.post(
            "/customer-projects/imports/preview",
            data={"file": (BytesIO(content), "history.xlsx")},
            content_type="multipart/form-data",
        )

    def test_preview_commit_retry_and_revert_only_valid_rows(self) -> None:
        content = self._workbook(
            [
                [
                    "历史客户",
                    "车载项目一期",
                    "域控制器",
                    120000,
                    "评估",
                    "sales@test.com",
                    "确认样品",
                    "2026-09-01 09:00",
                    "B",
                    30,
                ],
                [
                    "错误客户",
                    "错误项目",
                    "控制器",
                    -1,
                    "未知阶段",
                    "missing@test.com",
                    "等待",
                    "bad-date",
                    "Z",
                    25,
                ],
            ]
        )
        preview = self._preview(content)
        self.assertEqual(preview.status_code, 302)
        with app.app_context():
            batch = db.session.scalar(db.select(ProjectImportBatch))
            batch_id = batch.id
            self.assertEqual((batch.total_rows, batch.valid_rows, batch.error_rows), (2, 1, 1))
            self.assertEqual(db.session.query(CustomerProject).count(), 0)
            self.assertEqual(
                {row.status for row in db.session.scalars(db.select(ProjectImportRow))},
                {"valid", "invalid"},
            )

        detail = self.client.get(f"/customer-projects/imports?batch={batch_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("项目年用量必须大于 0", detail.get_data(as_text=True))
        committed = self.client.post(f"/customer-projects/imports/{batch_id}/commit")
        self.assertEqual(committed.status_code, 302)
        retry = self.client.post(f"/customer-projects/imports/{batch_id}/commit")
        self.assertEqual(retry.status_code, 302)
        with app.app_context():
            self.assertEqual(db.session.query(CustomerProject).count(), 1)
            self.assertEqual(db.session.query(Customer).count(), 1)
            project = db.session.scalar(db.select(CustomerProject))
            self.assertEqual(project.name, "车载项目一期")
            self.assertEqual(project.primary_sales_user_id, self.sales_id)

        reverted = self.client.post(f"/customer-projects/imports/{batch_id}/revert")
        self.assertEqual(reverted.status_code, 302)
        with app.app_context():
            batch = db.session.get(ProjectImportBatch, batch_id)
            self.assertEqual(batch.status, "reverted")
            self.assertIsNotNone(db.session.scalar(db.select(CustomerProject)).deleted_at)
            self.assertIsNotNone(db.session.scalar(db.select(Customer)).deleted_at)

    def test_revert_preserves_project_modified_after_import(self) -> None:
        content = self._workbook(
            [["客户二", "项目二", "控制器", 1000, "立项", "sales@test.com", "送样", "2026-09-02 09:00", "A", 70]]
        )
        self._preview(content)
        with app.app_context():
            batch_id = db.session.scalar(db.select(ProjectImportBatch.id))
        self.client.post(f"/customer-projects/imports/{batch_id}/commit")
        with app.app_context():
            project = db.session.scalar(db.select(CustomerProject))
            project.version += 1
            db.session.commit()
        self.client.post(f"/customer-projects/imports/{batch_id}/revert")
        with app.app_context():
            batch = db.session.get(ProjectImportBatch, batch_id)
            project = db.session.scalar(db.select(CustomerProject))
            row = db.session.scalar(db.select(ProjectImportRow))
            self.assertEqual(batch.status, "partially_reverted")
            self.assertEqual(row.status, "not_revertible")
            self.assertIsNone(project.deleted_at)

    def test_template_and_invalid_upload_are_controlled(self) -> None:
        template = self.client.get("/customer-projects/imports/template.xlsx")
        self.assertEqual(template.status_code, 200)
        self.assertEqual(
            template.mimetype,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        invalid = self.client.post(
            "/customer-projects/imports/preview",
            data={"file": (BytesIO(b"not-an-xlsx"), "history.xlsx")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn("文件不是有效的 XLSX", invalid.get_data(as_text=True))
        with app.app_context():
            self.assertEqual(db.session.query(ProjectImportBatch).count(), 0)


if __name__ == "__main__":
    unittest.main()
