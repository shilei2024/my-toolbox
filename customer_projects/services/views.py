"""Personal and organization-saved project filter views."""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from customer_projects.models import ProjectSavedView, ProjectStatusCatalog
from customer_projects.services.projects import add_audit, normalize_name
from extensions import db
from shared.models import OrganizationMembership


class SavedViewError(ValueError):
    pass


def _personal_namespace(user_id: int) -> str:
    return f"user:{user_id}"


def _is_organization_admin(membership: OrganizationMembership) -> bool:
    return "organization_admin" in membership.roles


def normalize_view_filters(
    organization_id: str, values: dict[str, str]
) -> dict[str, str]:
    query = str(values.get("q") or "").strip()[:100]
    stage = str(values.get("stage") or "").strip()[:32]
    if stage:
        exists = db.session.scalar(
            select(ProjectStatusCatalog.id).where(
                ProjectStatusCatalog.organization_id == organization_id,
                ProjectStatusCatalog.code == stage,
                ProjectStatusCatalog.is_active.is_(True),
            )
        )
        if exists is None:
            raise SavedViewError("保存视图包含无效项目阶段。")
    return {"q": query, "stage": stage}


def list_accessible_views(membership: OrganizationMembership) -> list[ProjectSavedView]:
    return list(
        db.session.scalars(
            select(ProjectSavedView)
            .where(
                ProjectSavedView.organization_id == membership.organization_id,
                or_(
                    ProjectSavedView.namespace_key == "organization",
                    ProjectSavedView.namespace_key == _personal_namespace(membership.user_id),
                ),
            )
            .order_by(ProjectSavedView.visibility.desc(), ProjectSavedView.name, ProjectSavedView.id)
        )
    )


def get_accessible_view(
    view_id: str, membership: OrganizationMembership
) -> ProjectSavedView | None:
    view = db.session.get(ProjectSavedView, view_id)
    if view is None or view.organization_id != membership.organization_id:
        return None
    if view.namespace_key not in {
        "organization",
        _personal_namespace(membership.user_id),
    }:
        return None
    return view


def create_saved_view(
    values: dict[str, str], membership: OrganizationMembership
) -> ProjectSavedView:
    name = str(values.get("name") or "").strip()
    if not name or len(name) > 80:
        raise SavedViewError("视图名称为必填项，且不能超过 80 个字符。")
    normalized = normalize_name(name)
    if not normalized:
        raise SavedViewError("视图名称无效。")
    visibility = str(values.get("visibility") or "personal").strip()
    if visibility not in {"personal", "organization"}:
        raise SavedViewError("视图可见范围无效。")
    if visibility == "organization" and not _is_organization_admin(membership):
        raise SavedViewError("只有组织管理员可以发布组织共享视图。")
    namespace = (
        "organization" if visibility == "organization" else _personal_namespace(membership.user_id)
    )
    filters = normalize_view_filters(membership.organization_id, values)
    duplicate = db.session.scalar(
        select(ProjectSavedView.id).where(
            ProjectSavedView.organization_id == membership.organization_id,
            ProjectSavedView.namespace_key == namespace,
            ProjectSavedView.normalized_name == normalized,
        )
    )
    if duplicate is not None:
        raise SavedViewError("当前范围已存在同名视图。")
    view = ProjectSavedView(
        organization_id=membership.organization_id,
        namespace_key=namespace,
        visibility=visibility,
        name=name,
        normalized_name=normalized,
        created_by_user_id=membership.user_id,
    )
    view.set_filters(filters)
    db.session.add(view)
    try:
        db.session.flush()
    except IntegrityError as exc:
        raise SavedViewError("当前范围已存在同名视图。") from exc
    add_audit(
        membership.organization_id,
        "project_saved_view",
        view.id,
        "created",
        membership.user_id,
        {"name": view.name, "visibility": visibility, "filters": filters},
    )
    return view


def can_delete_view(view: ProjectSavedView, membership: OrganizationMembership) -> bool:
    if view.organization_id != membership.organization_id:
        return False
    if view.visibility == "organization":
        return _is_organization_admin(membership)
    return view.namespace_key == _personal_namespace(membership.user_id)


def delete_saved_view(
    view: ProjectSavedView,
    membership: OrganizationMembership,
    expected_version: int,
) -> None:
    if not can_delete_view(view, membership):
        raise SavedViewError("当前角色不能删除此视图。")
    if expected_version != view.version:
        raise SavedViewError("视图已被更新，请刷新后重试。")
    safe = {
        "name": view.name,
        "visibility": view.visibility,
        "filters": view.filters,
        "version": view.version,
    }
    view_id = view.id
    db.session.delete(view)
    add_audit(
        membership.organization_id,
        "project_saved_view",
        view_id,
        "deleted",
        membership.user_id,
        safe,
    )
