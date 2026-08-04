"""Unified admin: Gallery module screens served by the Flask main site.

These routes render the Generation Service admin data (moderation, providers,
workflows, jobs, audit) inside the main-site admin console. Every write goes
through the same signed internal-viewer contract the Next.js BFF used, so the
Generation Service still enforces its own admin RBAC and optimistic locking.
"""
from __future__ import annotations

from typing import Any

from urllib.parse import urlparse

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from auth.decorators import admin_required
from utils.gallery_admin_client import (
    GalleryAdminError,
    gallery_admin_dashboard,
    gallery_delete_image,
    gallery_moderate_image,
    gallery_update_provider,
    gallery_update_workflow,
    localize_iso,
)

from . import admin_bp


@admin_bp.route("/gallery")
@login_required
@admin_required
def gallery():
    """Gallery module dashboard: overview, moderation, providers, workflows."""
    dashboard: dict[str, Any] | None = None
    gallery_error: str | None = None
    gallery_origin = _gallery_origin()
    try:
        dashboard = _localized(gallery_admin_dashboard(current_user.id))
    except GalleryAdminError as exc:
        gallery_error = exc.message
    return render_template(
        "admin/gallery.html",
        dashboard=dashboard,
        gallery_error=gallery_error,
        gallery_origin=gallery_origin,
    )


@admin_bp.route("/gallery/images/<string:image_id>/moderation", methods=["POST"])
@login_required
@admin_required
def gallery_moderate(image_id: str):
    decision = request.form.get("decision", "")
    expected = request.form.get("expected_updated_at", "")
    if decision not in {"approved", "rejected"} or not expected:
        flash("审核参数不完整，请刷新后重试。", "danger")
        return redirect(url_for("admin.gallery"))
    try:
        gallery_moderate_image(current_user.id, image_id, decision, expected)
        label = "已批准并进入公开发布流程" if decision == "approved" else "已拒绝并从公开发现路径移除"
        flash(f"作品 {label}。", "success")
    except GalleryAdminError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("admin.gallery"))


@admin_bp.route("/gallery/images/<string:image_id>/delete", methods=["POST"])
@login_required
@admin_required
def gallery_delete(image_id: str):
    try:
        gallery_delete_image(current_user.id, image_id)
        flash("作品已软删除。", "success")
    except GalleryAdminError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("admin.gallery"))


@admin_bp.route("/gallery/providers/<string:provider_id>", methods=["POST"])
@login_required
@admin_required
def gallery_update_provider_route(provider_id: str):
    status = request.form.get("status", "")
    expected = request.form.get("expected_updated_at", "")
    try:
        priority = int(request.form.get("priority", ""))
        if status not in {"active", "disabled"} or not 0 <= priority <= 10000:
            raise ValueError
    except ValueError:
        flash("Provider 参数不合法（状态 active/disabled，优先级 0–10000）。", "danger")
        return redirect(url_for("admin.gallery"))
    if not expected:
        flash("Provider 数据已过期，请刷新后重试。", "danger")
        return redirect(url_for("admin.gallery"))
    try:
        gallery_update_provider(current_user.id, provider_id, status, priority, expected)
        flash("Provider 已更新。", "success")
    except GalleryAdminError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("admin.gallery"))


@admin_bp.route("/gallery/workflows/<string:workflow_id>", methods=["POST"])
@login_required
@admin_required
def gallery_update_workflow_route(workflow_id: str):
    expected = request.form.get("expected_updated_at", "")
    try:
        sort_order = int(request.form.get("sort_order", ""))
        if not 0 <= sort_order <= 10000:
            raise ValueError
    except ValueError:
        flash("工作流排序必须是 0–10000 的整数。", "danger")
        return redirect(url_for("admin.gallery"))
    if not expected:
        flash("工作流数据已过期，请刷新后重试。", "danger")
        return redirect(url_for("admin.gallery"))
    try:
        gallery_update_workflow(
            current_user.id,
            workflow_id,
            is_enabled=request.form.get("is_enabled") == "on",
            sort_order=sort_order,
            expected_updated_at=expected,
        )
        flash("工作流已更新。", "success")
    except GalleryAdminError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("admin.gallery"))


def _localized(dashboard: dict[str, Any]) -> dict[str, Any]:
    """Add Asia/Shanghai display timestamps without mutating the API payload."""
    result = dict(dashboard)
    overview = dict(dashboard.get("overview") or {})
    result["overview"] = overview
    result["moderationQueue"] = [
        {**item, "createdAtLocal": localize_iso(item.get("createdAt")), "updatedAtLocal": localize_iso(item.get("updatedAt"))}
        for item in dashboard.get("moderationQueue") or []
    ]
    result["providers"] = [
        {**item, "updatedAtLocal": localize_iso(item.get("updatedAt")), "lastHealthAtLocal": localize_iso(item.get("lastHealthAt"))}
        for item in dashboard.get("providers") or []
    ]
    result["workflows"] = [
        {**item, "updatedAtLocal": localize_iso(item.get("updatedAt"))}
        for item in dashboard.get("workflows") or []
    ]
    result["recentJobs"] = [
        {**item, "createdAtLocal": localize_iso(item.get("createdAt")), "finishedAtLocal": localize_iso(item.get("finishedAt"))}
        for item in dashboard.get("recentJobs") or []
    ]
    result["recentAudit"] = [
        {**item, "createdAtLocal": localize_iso(item.get("createdAt"))}
        for item in dashboard.get("recentAudit") or []
    ]
    return result


def _gallery_origin() -> str | None:
    """Public Gallery origin used for moderation preview links."""
    parsed = urlparse(str(current_app.config.get("AI_IMAGE_EXTERNAL_URL", "") or ""))
    if parsed.scheme == "https" and parsed.hostname:
        return f"https://{parsed.hostname}"
    return None
