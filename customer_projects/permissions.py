"""Server-side authorization for the customer project domain."""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from flask import abort, current_app, request
from flask_login import current_user
from sqlalchemy import exists, or_, select

from extensions import db
from shared.models import OrganizationMembership

ADMIN_ROLES = frozenset({"organization_admin", "business_manager"})
WRITE_ROLES = frozenset({"organization_admin", "business_manager", "sales", "pm", "fae"})
PRICE_EDIT_ROLES = frozenset({"organization_admin", "business_manager", "sales", "pm"})


def _pilot_allows_current_user() -> bool:
    raw = str(current_app.config.get("CUSTOMER_PROJECTS_PILOT_EMAILS", ""))
    pilots = {item.strip().casefold() for item in raw.split(",") if item.strip()}
    return not pilots or str(getattr(current_user, "email", "")).casefold() in pilots


def current_membership() -> OrganizationMembership | None:
    if not current_user.is_authenticated or not current_user.is_active:
        return None
    return db.session.scalar(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.user_id == current_user.id,
            OrganizationMembership.status == "active",
        )
        .order_by(OrganizationMembership.created_at.asc())
        .limit(1)
    )


def module_available() -> bool:
    if not current_app.config.get("CUSTOMER_PROJECTS_ENABLED", False):
        return False
    if not current_user.is_authenticated or not _pilot_allows_current_user():
        return False
    return current_membership() is not None


def module_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not current_user.is_authenticated:
            abort(401 if request.path.startswith("/api/") else 403)
        if not current_app.config.get("CUSTOMER_PROJECTS_ENABLED", False):
            abort(404)
        if not _pilot_allows_current_user():
            abort(404)
        membership = current_membership()
        if membership is None:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def require_write(membership: OrganizationMembership) -> None:
    if not can_write(membership):
        abort(403)


def can_write(membership: OrganizationMembership) -> bool:
    return bool(membership.roles.intersection(WRITE_ROLES))


def require_manager(membership: OrganizationMembership) -> None:
    if not membership.roles.intersection(ADMIN_ROLES):
        abort(403)


def can_edit_prices(membership: OrganizationMembership) -> bool:
    return bool(membership.roles.intersection(PRICE_EDIT_ROLES))


def require_price_edit(membership: OrganizationMembership) -> None:
    if not can_edit_prices(membership):
        abort(403)


def can_view_project(membership: OrganizationMembership, project: Any) -> bool:
    if project.organization_id != membership.organization_id:
        return False
    if membership.roles.intersection(ADMIN_ROLES):
        return True
    if project.primary_sales_user_id == membership.user_id:
        return True
    from customer_projects.models import ProjectMember  # local import avoids cycles

    return db.session.scalar(
        select(ProjectMember.id).where(
            ProjectMember.organization_id == membership.organization_id,
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == membership.user_id,
            ProjectMember.left_at.is_(None),
        )
    ) is not None


def apply_project_scope(statement: Any, membership: OrganizationMembership) -> Any:
    """Apply tenant and member-level visibility to a CustomerProject select."""
    from customer_projects.models import CustomerProject, ProjectMember

    statement = statement.where(CustomerProject.organization_id == membership.organization_id)
    if membership.roles.intersection(ADMIN_ROLES):
        return statement
    member_exists = exists().where(
        ProjectMember.project_id == CustomerProject.id,
        ProjectMember.organization_id == membership.organization_id,
        ProjectMember.user_id == membership.user_id,
        ProjectMember.left_at.is_(None),
    )
    return statement.where(
        or_(CustomerProject.primary_sales_user_id == membership.user_id, member_exists)
    )
