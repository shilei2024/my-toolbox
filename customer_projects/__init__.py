"""Customer project tracking Flask blueprint."""
from __future__ import annotations

from datetime import datetime, timezone

import click
from flask import Blueprint, current_app
from sqlalchemy import select

customer_projects_bp = Blueprint(
    "customer_projects",
    __name__,
    url_prefix="/customer-projects",
    template_folder="../templates",
    cli_group="customer-projects",
)
customer_projects_api_bp = Blueprint(
    "customer_projects_api",
    __name__,
    url_prefix="/api/v1/customer-projects",
)

# Import models before app schema initialization and routes for registration.
from shared import models as shared_models  # noqa: E402,F401
from . import models as domain_models  # noqa: E402,F401
from . import api, routes  # noqa: E402,F401


@customer_projects_bp.app_context_processor
def inject_customer_projects_access():
    from .permissions import ADMIN_ROLES, current_membership, module_available

    try:
        available = module_available()
        membership = current_membership() if available else None
        can_manage = bool(membership and membership.roles.intersection(ADMIN_ROLES))
    except Exception:  # database outages must not break unrelated pages
        available = False
        can_manage = False
    return {
        "customer_projects_available": available,
        "customer_projects_can_manage": can_manage,
    }


@customer_projects_bp.cli.command("bootstrap")
@click.option("--admin-email", required=True, help="Existing platform admin email.")
@click.option("--name", default=None, help="Organization display name.")
def bootstrap_command(admin_email: str, name: str | None) -> None:
    """Create the first organization, admin membership and status dictionary."""
    from extensions import db
    from models import User
    from .services.projects import bootstrap_organization

    user = db.session.scalar(select(User).where(User.email == admin_email.strip().lower()))
    if user is None or not user.is_admin or not user.is_active_user:
        raise click.ClickException("找不到有效的平台管理员账号。")
    org = bootstrap_organization(
        name or current_app.config["CUSTOMER_PROJECTS_DEFAULT_ORG_NAME"], user.id
    )
    click.echo(f"customer projects organization ready: {org.id}")


@customer_projects_bp.cli.command("scan-reminders")
@click.option("--organization-id", default=None, help="Optional organization UUID.")
@click.option("--force", is_flag=True, help="Allow a controlled local/staging scan while the global switch is off.")
@click.option("--now", "now_value", default=None, help="Override scan time with an ISO-8601 UTC timestamp.")
def scan_reminders_command(organization_id: str | None, force: bool, now_value: str | None) -> None:
    """Scan due/stale projects and create idempotent notification intents."""
    if not current_app.config.get("CUSTOMER_PROJECT_REMINDERS_ENABLED", False) and not force:
        raise click.ClickException("CUSTOMER_PROJECT_REMINDERS_ENABLED=false; scan not started")
    from .services.reminders import scan_project_reminders

    scan_now = None
    if now_value:
        try:
            scan_now = datetime.fromisoformat(now_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise click.ClickException("--now must be an ISO-8601 timestamp, for example 2026-08-28T02:00:00Z") from exc
        if scan_now.tzinfo is None:
            scan_now = scan_now.replace(tzinfo=timezone.utc)

    result = scan_project_reminders(now=scan_now, organization_id=organization_id)
    click.echo(f"scanned={result['scanned']} created={result['created']} limited={result['limited']}")


@customer_projects_bp.cli.command("dispatch-notifications")
@click.option("--limit", default=100, type=click.IntRange(1, 500))
@click.option("--now", "now_value", default=None, help="Override dispatch time with an ISO-8601 UTC timestamp.")
def dispatch_notifications_command(limit: int, now_value: str | None) -> None:
    """Claim due outbox rows and deliver through dry-run or configured SMTP."""
    from shared.notifications import dispatch_due_notifications

    dispatch_now = None
    if now_value:
        try:
            dispatch_now = datetime.fromisoformat(now_value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise click.ClickException("--now must be an ISO-8601 timestamp, for example 2026-08-28T02:00:00Z") from exc
        if dispatch_now.tzinfo is None:
            dispatch_now = dispatch_now.replace(tzinfo=timezone.utc)

    result = dispatch_due_notifications(now=dispatch_now, limit=limit)
    click.echo(f"claimed={result['claimed']} sent={result['sent']} failed={result['failed']}")
