"""Stable JSON API for customer project tracking."""
from __future__ import annotations

from datetime import date, datetime

from flask import g, jsonify, request
from sqlalchemy import select

from extensions import db

from . import customer_projects_api_bp
from .models import Customer, CustomerProject, ProjectActivity, ProjectMaterial
from .permissions import apply_project_scope, can_view_project, current_membership, module_required, require_manager, require_price_edit, require_write
from .services.projects import (
    DomainError,
    VersionConflict,
    add_activity,
    add_competitor,
    add_material,
    create_project,
    restore_project,
    soft_delete_project,
    transition_stage,
    update_project,
    update_material_commercial,
)


def _membership():
    membership = current_membership()
    if membership is None:
        return None
    return membership


def _serialize_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def project_json(project: CustomerProject, *, include_customer: bool = False) -> dict:
    data = {
        "id": project.id,
        "project_code": project.project_code,
        "customer_id": project.customer_id,
        "name": project.name,
        "product_name": project.product_name,
        "annual_usage": str(project.annual_usage) if project.annual_usage is not None else None,
        "stage_code": project.stage_code,
        "assessment_grade": project.assessment_grade,
        "probability_band": project.probability_band,
        "primary_sales_user_id": project.primary_sales_user_id,
        "next_action": project.next_action,
        "next_follow_up_at": _serialize_value(project.next_follow_up_at),
        "last_meaningful_update_at": _serialize_value(project.last_meaningful_update_at),
        "expected_design_win_at": _serialize_value(project.expected_design_win_at),
        "expected_mass_production_at": _serialize_value(project.expected_mass_production_at),
        "version": project.version,
        "updated_at": _serialize_value(project.updated_at),
    }
    if include_customer:
        customer = db.session.get(Customer, project.customer_id)
        data["customer"] = {"id": customer.id, "name": customer.name} if customer else None
    return data


def _error(exc: DomainError, status: int = 422):
    details = {"current_version": exc.current_version} if isinstance(exc, VersionConflict) else {}
    conflict = isinstance(exc, VersionConflict) or exc.code == "MATERIAL_VERSION_CONFLICT"
    return jsonify(error={"code": exc.code, "message": exc.message, "field_errors": exc.field_errors, "request_id": getattr(g, "request_id", None), "details": details}), (409 if conflict else status)


@customer_projects_api_bp.get("/projects")
@module_required
def list_projects():
    membership = _membership()
    statement = apply_project_scope(select(CustomerProject).where(CustomerProject.deleted_at.is_(None)), membership)
    limit = min(max(request.args.get("limit", 25, type=int), 1), 100)
    rows = list(db.session.scalars(statement.order_by(CustomerProject.updated_at.desc(), CustomerProject.id).limit(limit)))
    return jsonify(data=[project_json(row, include_customer=True) for row in rows], meta={"limit": limit})


@customer_projects_api_bp.post("/projects")
@module_required
def api_create_project():
    membership = _membership()
    require_write(membership)
    try:
        project = create_project(request.get_json(silent=True) or {}, membership, request.headers.get("Idempotency-Key", ""))
        db.session.commit()
        response = jsonify(data=project_json(project, include_customer=True))
        response.status_code = 201
        response.headers["ETag"] = f'"{project.version}"'
        response.headers["Location"] = f"/api/v1/customer-projects/projects/{project.id}"
        return response
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)


@customer_projects_api_bp.get("/projects/<string:project_id>")
@module_required
def api_get_project(project_id: str):
    membership = _membership()
    project = db.session.get(CustomerProject, project_id)
    if project is None or project.deleted_at is not None or not can_view_project(membership, project):
        return jsonify(error={"code": "NOT_FOUND", "message": "项目不存在或不可访问。"}), 404
    response = jsonify(data=project_json(project, include_customer=True))
    response.headers["ETag"] = f'"{project.version}"'
    return response


def _if_match_version() -> int | None:
    raw = request.headers.get("If-Match", "").strip().strip('"')
    try:
        return int(raw)
    except ValueError:
        return None


@customer_projects_api_bp.patch("/projects/<string:project_id>")
@module_required
def api_update_project(project_id: str):
    membership = _membership()
    require_write(membership)
    project = db.session.get(CustomerProject, project_id)
    if project is None or project.deleted_at is not None or not can_view_project(membership, project):
        return jsonify(error={"code": "NOT_FOUND", "message": "项目不存在或不可访问。"}), 404
    expected = _if_match_version()
    if expected is None:
        return jsonify(error={"code": "IF_MATCH_REQUIRED", "message": "更新项目必须携带 If-Match 版本。"}), 428
    try:
        updated = update_project(project, request.get_json(silent=True) or {}, membership, expected)
        db.session.commit()
        response = jsonify(data=project_json(updated, include_customer=True))
        response.headers["ETag"] = f'"{updated.version}"'
        return response
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)


@customer_projects_api_bp.post("/projects/<string:project_id>/activities")
@module_required
def api_add_activity(project_id: str):
    membership = _membership()
    require_write(membership)
    project = db.session.get(CustomerProject, project_id)
    if project is None or project.deleted_at is not None or not can_view_project(membership, project):
        return jsonify(error={"code": "NOT_FOUND", "message": "项目不存在或不可访问。"}), 404
    try:
        activity = add_activity(project, request.get_json(silent=True) or {}, membership, request.headers.get("Idempotency-Key", ""))
        db.session.commit()
        current = db.session.get(CustomerProject, project.id)
        response = jsonify(data={"id": activity.id, "project_id": activity.project_id, "version": current.version})
        response.status_code = 201
        response.headers["ETag"] = f'"{current.version}"'
        return response
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)


@customer_projects_api_bp.post("/projects/<string:project_id>/stage-transitions")
@module_required
def api_transition_stage(project_id: str):
    membership = _membership()
    require_write(membership)
    project = db.session.get(CustomerProject, project_id)
    if project is None or project.deleted_at is not None or not can_view_project(membership, project):
        return jsonify(error={"code": "NOT_FOUND", "message": "项目不存在或不可访问。"}), 404
    data = request.get_json(silent=True) or {}
    if data.get("to_stage_code") in {"mass_production", "lost"}:
        require_manager(membership)
    try:
        event = transition_stage(project, data, membership, request.headers.get("Idempotency-Key", ""))
        db.session.commit()
        current = db.session.get(CustomerProject, project.id)
        response = jsonify(data={"id": event.id, "from_stage_code": event.from_stage_code, "to_stage_code": event.to_stage_code, "version": current.version})
        response.status_code = 201
        response.headers["ETag"] = f'"{current.version}"'
        return response
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)


@customer_projects_api_bp.post("/projects/<string:project_id>/materials")
@module_required
def api_add_material(project_id: str):
    membership = _membership()
    require_write(membership)
    project = db.session.get(CustomerProject, project_id)
    if project is None or project.deleted_at is not None or not can_view_project(membership, project):
        return jsonify(error={"code": "NOT_FOUND", "message": "项目不存在或不可访问。"}), 404
    try:
        payload = request.get_json(silent=True) or {}
        if payload.get("unit_price") not in (None, ""):
            require_price_edit(membership)
        material = add_material(
            project,
            payload,
            membership,
            request.headers.get("Idempotency-Key", ""),
        )
        db.session.commit()
        return jsonify(data={
            "id": material.id,
            "project_id": material.project_id,
            "machine_quantity": str(material.machine_quantity) if material.machine_quantity is not None else None,
            "unit_price_usd": str(material.unit_price_usd) if material.unit_price_usd is not None else None,
            "unit_price_cny_tax_included": str(material.unit_price_cny_tax_included) if material.unit_price_cny_tax_included is not None else None,
            "fx_rate_usd_cny": str(material.fx_rate_usd_cny) if material.fx_rate_usd_cny is not None else None,
            "version": material.version,
        }), 201
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)


@customer_projects_api_bp.patch("/materials/<string:material_id>")
@module_required
def api_update_material_commercial(material_id: str):
    membership = _membership()
    require_write(membership)
    material = db.session.scalar(
        select(ProjectMaterial).where(
            ProjectMaterial.id == material_id,
            ProjectMaterial.organization_id == membership.organization_id,
            ProjectMaterial.deleted_at.is_(None),
        )
    )
    if material is None:
        return jsonify(error={"code": "NOT_FOUND", "message": "推广物料不存在或不可访问。"}), 404
    project = db.session.get(CustomerProject, material.project_id)
    if project is None or not can_view_project(membership, project):
        return jsonify(error={"code": "NOT_FOUND", "message": "推广物料不存在或不可访问。"}), 404
    expected = _if_match_version()
    if expected is None:
        return jsonify(error={"code": "IF_MATCH_REQUIRED", "message": "更新物料必须携带 If-Match 版本。"}), 428
    try:
        payload = request.get_json(silent=True) or {}
        if payload.get("unit_price") not in (None, ""):
            require_price_edit(membership)
        updated = update_material_commercial(
            material, payload, membership, expected
        )
        db.session.commit()
        response = jsonify(data={
            "id": updated.id,
            "machine_quantity": str(updated.machine_quantity) if updated.machine_quantity is not None else None,
            "unit_price_usd": str(updated.unit_price_usd) if updated.unit_price_usd is not None else None,
            "unit_price_cny_tax_included": str(updated.unit_price_cny_tax_included) if updated.unit_price_cny_tax_included is not None else None,
            "fx_rate_usd_cny": str(updated.fx_rate_usd_cny) if updated.fx_rate_usd_cny is not None else None,
            "version": updated.version,
        })
        response.headers["ETag"] = f'"{updated.version}"'
        return response
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)


@customer_projects_api_bp.post("/materials/<string:material_id>/competitors")
@module_required
def api_add_competitor(material_id: str):
    membership = _membership()
    require_write(membership)
    material = db.session.scalar(
        select(ProjectMaterial).where(
            ProjectMaterial.id == material_id,
            ProjectMaterial.organization_id == membership.organization_id,
            ProjectMaterial.deleted_at.is_(None),
        )
    )
    if material is None:
        return jsonify(error={"code": "NOT_FOUND", "message": "推广物料不存在或不可访问。"}), 404
    project = db.session.get(CustomerProject, material.project_id)
    if project is None or not can_view_project(membership, project):
        return jsonify(error={"code": "NOT_FOUND", "message": "推广物料不存在或不可访问。"}), 404
    try:
        competitor = add_competitor(
            material,
            request.get_json(silent=True) or {},
            membership,
            request.headers.get("Idempotency-Key", ""),
        )
        db.session.commit()
        return jsonify(data={"id": competitor.id, "project_material_id": competitor.project_material_id, "version": competitor.version}), 201
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)


@customer_projects_api_bp.delete("/projects/<string:project_id>")
@module_required
def api_delete_project(project_id: str):
    membership = _membership()
    require_write(membership)
    project = db.session.get(CustomerProject, project_id)
    if project is None or project.deleted_at is not None or not can_view_project(membership, project):
        return jsonify(error={"code": "NOT_FOUND", "message": "项目不存在或不可访问。"}), 404
    expected = _if_match_version()
    if expected is None:
        return jsonify(error={"code": "IF_MATCH_REQUIRED", "message": "删除项目必须携带 If-Match 版本。"}), 428
    try:
        soft_delete_project(project, str((request.get_json(silent=True) or {}).get("reason") or ""), membership, expected)
        db.session.commit()
        return "", 204
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)


@customer_projects_api_bp.post("/trash/projects/<string:project_id>/restore")
@module_required
def api_restore_project(project_id: str):
    membership = _membership()
    require_manager(membership)
    project = db.session.scalar(
        select(CustomerProject).where(
            CustomerProject.id == project_id,
            CustomerProject.organization_id == membership.organization_id,
            CustomerProject.deleted_at.is_not(None),
        )
    )
    if project is None:
        return jsonify(error={"code": "NOT_FOUND", "message": "回收站项目不存在。"}), 404
    try:
        restore_project(project, membership)
        db.session.commit()
        return jsonify(data=project_json(project, include_customer=True))
    except DomainError as exc:
        db.session.rollback()
        return _error(exc)
