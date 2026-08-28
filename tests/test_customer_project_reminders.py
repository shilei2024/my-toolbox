"""Phase 2 reminder rules, outbox idempotency and dry-run delivery tests."""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone

os.environ["FLASK_ENV"] = "production"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "phase-2-test-secret-key-that-is-long-enough"
os.environ["ADMIN_EMAIL"] = "bootstrap@test.com"
os.environ["ADMIN_PASSWORD"] = "SafeBootstrapPassword123!"

from app import app  # noqa: E402
from customer_projects.models import CustomerProject, ProjectMember, ProjectReminderOverride, ProjectReminderPolicy  # noqa: E402
from customer_projects.services.projects import (  # noqa: E402
    add_activity,
    bootstrap_organization,
    create_customer,
    create_project,
)
from customer_projects.services.reminders import scan_project_reminders  # noqa: E402
from extensions import db  # noqa: E402
from models import User  # noqa: E402
from shared.models import (  # noqa: E402
    NotificationDelivery,
    NotificationOutbox,
    NotificationWorkerHeartbeat,
    OrganizationMembership,
)
from shared.notifications import dispatch_due_notifications  # noqa: E402


class CustomerProjectReminderTest(unittest.TestCase):
    NOW = datetime(2026, 8, 28, 2, 0, tzinfo=timezone.utc)  # Friday 10:00 China

    def setUp(self) -> None:
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            CUSTOMER_PROJECTS_ENABLED=True,
            CUSTOMER_PROJECT_REMINDERS_ENABLED=True,
            CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=False,
            NOTIFICATION_ADAPTER="dry-run",
            APP_BASE_URL="https://toolbox.test",
        )
        with app.app_context():
            db.drop_all()
            db.create_all()
            self.manager_id = self._add_user("manager@test.com", admin=True)
            self.sales_id = self._add_user("sales@test.com")
            self.pm_id = self._add_user("pm@test.com")
            self.inactive_id = self._add_user("inactive@test.com", active=False)
            org = bootstrap_organization("提醒测试组织", self.manager_id)
            self.org_id = org.id
            self._add_membership(self.sales_id, {"sales"})
            self._add_membership(self.pm_id, {"pm"})
            self._add_membership(self.inactive_id, {"pm"})
            policy = ProjectReminderPolicy(
                organization_id=org.id,
                is_enabled=True,
                include_pm=True,
                daily_limit=100,
            )
            db.session.add(policy)
            db.session.commit()

    def _add_user(self, email: str, *, admin: bool = False, active: bool = True) -> int:
        user = User(email=email, is_admin=admin, is_active_user=active)
        user.set_password("Passw0rd1")
        db.session.add(user)
        db.session.flush()
        return user.id

    def _add_membership(self, user_id: int, roles: set[str]) -> None:
        membership = OrganizationMembership(
            organization_id=self.org_id,
            user_id=user_id,
            status="active",
        )
        membership.set_roles(roles)
        db.session.add(membership)

    def _seed_project(self, *, followup: datetime, meaningful: datetime) -> str:
        membership = db.session.scalar(
            db.select(OrganizationMembership).where(
                OrganizationMembership.user_id == self.sales_id
            )
        )
        customer = create_customer({"name": "提醒客户"}, membership)
        db.session.flush()
        project = create_project(
            {
                "customer_id": customer.id,
                "name": "提醒测试项目",
                "product_name": "控制器",
                "annual_usage": "10000",
                "stage_code": "evaluation",
                "primary_sales_user_id": self.sales_id,
                "next_action": "确认样品计划",
                "next_follow_up_at": followup.isoformat(),
            },
            membership,
            f"project-{followup.isoformat()}",
        )
        project.last_meaningful_update_at = meaningful
        from customer_projects.models import ProjectMember

        db.session.add(
            ProjectMember(
                organization_id=self.org_id,
                project_id=project.id,
                user_id=self.pm_id,
                role_code="pm",
            )
        )
        db.session.commit()
        return project.id

    def test_repeated_scan_is_idempotent_and_dry_run_is_traceable(self) -> None:
        with app.app_context():
            project_id = self._seed_project(
                followup=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
                meaningful=self.NOW,
            )
            results = [scan_project_reminders(self.NOW) for _ in range(10)]
            self.assertEqual(results[0]["created"], 2)
            self.assertTrue(all(result["created"] == 0 for result in results[1:]))
            rows = list(db.session.scalars(db.select(NotificationOutbox)))
            self.assertEqual({row.event_type for row in rows}, {"followup_pre_due", "followup_due"})
            self.assertTrue(all(row.object_id == project_id for row in rows))
            self.assertEqual(db.session.query(NotificationDelivery).count(), 4)
            self.assertNotIn("inactive@test.com", {row.recipient_address for row in db.session.scalars(db.select(NotificationDelivery))})

            dispatched = dispatch_due_notifications(self.NOW)
            self.assertEqual(dispatched, {"claimed": 2, "sent": 2, "failed": 0})
            self.assertEqual(
                {row.status for row in db.session.scalars(db.select(NotificationOutbox))},
                {"sent"},
            )
            self.assertTrue(
                all(
                    row.provider_message_id.startswith("dry-run:")
                    for row in db.session.scalars(db.select(NotificationDelivery))
                )
            )
            heartbeat = db.session.get(NotificationWorkerHeartbeat, "notification-dispatch")
            self.assertEqual(heartbeat.status, "ok")

    def test_meaningful_activity_cancels_unsent_old_reminders(self) -> None:
        with app.app_context():
            project_id = self._seed_project(
                followup=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
                meaningful=self.NOW,
            )
            scan_project_reminders(self.NOW)
            project = db.session.get(CustomerProject, project_id)
            membership = db.session.scalar(
                db.select(OrganizationMembership).where(
                    OrganizationMembership.user_id == self.sales_id
                )
            )
            add_activity(
                project,
                {
                    "activity_type": "call",
                    "summary": "已完成本轮跟进",
                    "next_action": "准备报价",
                    "next_follow_up_at": (self.NOW + timedelta(days=5)).isoformat(),
                    "project_version": project.version,
                    "is_meaningful": True,
                },
                membership,
                "activity-cancels-reminders",
            )
            db.session.commit()
            self.assertEqual(
                {row.status for row in db.session.scalars(db.select(NotificationOutbox))},
                {"cancelled"},
            )
            self.assertEqual(dispatch_due_notifications(self.NOW)["claimed"], 0)

    def test_stale_escalation_adds_active_manager_only(self) -> None:
        with app.app_context():
            self._seed_project(
                followup=self.NOW + timedelta(days=30),
                meaningful=self.NOW - timedelta(days=20),
            )
            result = scan_project_reminders(self.NOW)
            self.assertEqual(result["created"], 2)
            outboxes = {
                row.event_type: row
                for row in db.session.scalars(db.select(NotificationOutbox))
            }
            primary_recipients = {
                row.recipient_user_id
                for row in db.session.scalars(
                    db.select(NotificationDelivery).where(
                        NotificationDelivery.outbox_id == outboxes["stale_primary"].id
                    )
                )
            }
            manager_recipients = {
                row.recipient_user_id
                for row in db.session.scalars(
                    db.select(NotificationDelivery).where(
                        NotificationDelivery.outbox_id == outboxes["stale_manager"].id
                    )
                )
            }
            self.assertEqual(primary_recipients, {self.sales_id, self.pm_id})
            self.assertEqual(manager_recipients, {self.manager_id, self.sales_id, self.pm_id})
            self.assertNotIn(self.inactive_id, manager_recipients)

    def test_smtp_adapter_requires_explicit_live_delivery_switch(self) -> None:
        with app.app_context():
            self._seed_project(
                followup=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
                meaningful=self.NOW,
            )
            scan_project_reminders(self.NOW)
            app.config["NOTIFICATION_ADAPTER"] = "smtp"
            app.config["CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED"] = False
            result = dispatch_due_notifications(self.NOW)
            self.assertEqual(result, {"claimed": 2, "sent": 0, "failed": 2})
            outboxes = list(db.session.scalars(db.select(NotificationOutbox)))
            self.assertEqual({row.status for row in outboxes}, {"failed"})
            self.assertEqual(
                {row.last_error_code for row in outboxes}, {"LIVE_DELIVERY_DISABLED"}
            )
            app.config.update(
                CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=True,
                SMTP_HOST="smtp.invalid",
                SMTP_FROM="projects@test.com",
                SMTP_SECURITY="none",
            )
            retried = dispatch_due_notifications(self.NOW + timedelta(minutes=3))
            self.assertEqual(retried, {"claimed": 2, "sent": 0, "failed": 2})
            self.assertEqual(
                {
                    row.last_error_code
                    for row in db.session.scalars(db.select(NotificationOutbox))
                },
                {"SMTP_SECURITY_INVALID"},
            )

    def test_scheduler_cli_respects_global_scan_switch(self) -> None:
        runner = app.test_cli_runner()
        app.config["CUSTOMER_PROJECT_REMINDERS_ENABLED"] = False
        blocked = runner.invoke(args=["customer-projects", "scan-reminders"])
        self.assertNotEqual(blocked.exit_code, 0)
        self.assertIn("CUSTOMER_PROJECT_REMINDERS_ENABLED=false", blocked.output)
        app.config["CUSTOMER_PROJECT_REMINDERS_ENABLED"] = True
        scanned = runner.invoke(args=["customer-projects", "scan-reminders"])
        self.assertEqual(scanned.exit_code, 0)
        self.assertIn("scanned=0 created=0 limited=0", scanned.output)
        dispatched = runner.invoke(
            args=["customer-projects", "dispatch-notifications", "--limit", "10"]
        )
        self.assertEqual(dispatched.exit_code, 0)
        self.assertIn("claimed=0 sent=0 failed=0", dispatched.output)

    def test_project_override_and_member_email_opt_out(self) -> None:
        with app.app_context():
            project_id = self._seed_project(
                followup=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
                meaningful=self.NOW,
            )
            override = ProjectReminderOverride(
                organization_id=self.org_id,
                project_id=project_id,
                is_enabled=False,
                include_pm=True,
            )
            db.session.add(override)
            db.session.commit()
            self.assertEqual(scan_project_reminders(self.NOW)["created"], 0)

            override.is_enabled = True
            override.version += 1
            pm_member = db.session.scalar(
                db.select(ProjectMember).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == self.pm_id,
                )
            )
            pm_member.notification_preferences_json = '{"email_enabled": false}'
            db.session.commit()
            self.assertEqual(scan_project_reminders(self.NOW)["created"], 2)
            self.assertEqual(
                {
                    row.recipient_user_id
                    for row in db.session.scalars(db.select(NotificationDelivery))
                },
                {self.sales_id},
            )

if __name__ == "__main__":
    unittest.main()
