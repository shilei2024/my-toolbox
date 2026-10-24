"""Unified admin: Gallery module screens served by the Flask main site.

These routes render the Generation Service admin data (moderation, providers,
workflows, jobs, audit) inside the main-site admin console. Every write goes
through the same signed internal-viewer contract the Next.js BFF used, so the
Generation Service still enforces its own admin RBAC and optimistic locking.
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from urllib.parse import urlparse

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from auth.decorators import admin_required
from utils.gallery_admin_client import (
    GalleryAdminError,
    gallery_admin_dashboard,
    gallery_create_curated_image,
    gallery_delete_curated_image,
    gallery_delete_image,
    gallery_list_curated_images,
    gallery_moderate_image,
    gallery_update_curated_image,
    gallery_update_provider,
    gallery_update_workflow,
    localize_iso,
)

from . import admin_bp

# The main-site admin runs as a Vercel Function with a 4.5 MB request limit.
CURATED_MAX_FILE_MB = 4
CURATED_UPLOAD_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
CURATED_MODEL_MAX = 128


@admin_bp.route("/gallery")
@login_required
@admin_required
def gallery():
    """Gallery module dashboard: overview, moderation, providers, workflows, curated uploads."""
    dashboard: dict[str, Any] | None = None
    gallery_error: str | None = None
    gallery_origin = _gallery_origin()
    try:
        dashboard = _localized(gallery_admin_dashboard(current_user.id))
    except GalleryAdminError as exc:
        gallery_error = exc.message
    curated_images: list[dict[str, Any]] = []
    curated_error: str | None = None
    if dashboard is not None:
        try:
            curated_images = _localized_curated(
                (gallery_list_curated_images(current_user.id) or {}).get("items") or []
            )
        except GalleryAdminError as exc:
            curated_error = exc.message
    return render_template(
        "admin/gallery.html",
        dashboard=dashboard,
        gallery_error=gallery_error,
        gallery_origin=gallery_origin,
        curated_images=curated_images,
        curated_error=curated_error,
        curated_max_mb=CURATED_MAX_FILE_MB,
    )


@admin_bp.route("/gallery/curated", methods=["POST"])
@login_required
@admin_required
def gallery_curated_upload():
    """Publish an admin-uploaded image together with the prompt that produced it."""
    upload = request.files.get("image")
    prompt = request.form.get("prompt") or ""
    model = (request.form.get("model") or "").strip()
    title = (request.form.get("title") or "").strip()
    negative_prompt = request.form.get("negative_prompt") or ""
    description = (request.form.get("description") or "").strip()
    prompt_visibility = request.form.get("prompt_visibility") or "public"

    if upload is None or not upload.filename:
        flash("请选择要发布的图片文件。", "danger")
        return redirect(url_for("admin.gallery"))
    extension = (upload.filename.rsplit(".", 1)[-1] if "." in upload.filename else "").lower()
    mime_type = CURATED_UPLOAD_TYPES.get(extension)
    if mime_type is None:
        flash("仅支持 JPG / PNG / WebP 图片。", "danger")
        return redirect(url_for("admin.gallery"))
    if not prompt.strip():
        flash("提示词不能为空：策展作品的提示词会原样保留并公开展示。", "danger")
        return redirect(url_for("admin.gallery"))
    if not model or len(model) > CURATED_MODEL_MAX:
        flash("请填写模型名称（1–128 个字符），它会作为画廊的模型筛选项。", "danger")
        return redirect(url_for("admin.gallery"))

    limit_bytes = _curated_upload_limit()
    payload = upload.read(limit_bytes + 1)
    if len(payload) > limit_bytes:
        flash(f"图片超过 {_curated_upload_limit_mb()}MB 上限。", "danger")
        return redirect(url_for("admin.gallery"))
    if not _matches_signature(payload, extension):
        flash("文件内容与扩展名不匹配，请重新导出后再上传。", "danger")
        return redirect(url_for("admin.gallery"))

    tags = [item for item in re.split(r"[,，]", request.form.get("tags") or "") if item.strip()]
    encoded = base64.b64encode(payload).decode("ascii")
    try:
        gallery_create_curated_image(
            current_user.id,
            image_base64=f"data:{mime_type};base64,{encoded}",
            title=title,
            prompt=prompt,
            model=model,
            negative_prompt=negative_prompt,
            description=description,
            tags=[tag.strip() for tag in tags][:8],
            prompt_visibility=prompt_visibility,
        )
        flash("策展作品已发布到画廊，提示词已保存。", "success")
    except GalleryAdminError as exc:
        flash(exc.message, "danger")
    except (binascii.Error, ValueError):
        flash("图片编码失败，请重新上传。", "danger")
    return redirect(url_for("admin.gallery"))


@admin_bp.route("/gallery/curated/<string:image_id>/update", methods=["POST"])
@login_required
@admin_required
def gallery_curated_update(image_id: str):
    fields: dict[str, Any] = {}
    for form_key, api_key in (("title", "title"), ("prompt", "prompt"), ("model", "model"), ("description", "description"), ("negative_prompt", "negativePrompt")):
        value = request.form.get(form_key)
        if value is not None and value.strip():
            fields[api_key] = value if api_key in {"prompt", "negativePrompt"} else value.strip()
    raw_tags = request.form.get("tags")
    if raw_tags is not None and raw_tags.strip():
        fields["tags"] = [tag.strip() for tag in re.split(r"[,，]", raw_tags) if tag.strip()][:8]
    visibility = request.form.get("prompt_visibility")
    if visibility in {"public", "hidden"}:
        fields["promptVisibility"] = visibility
    if not fields:
        flash("没有需要更新的内容。", "warning")
        return redirect(url_for("admin.gallery"))
    try:
        gallery_update_curated_image(current_user.id, image_id, fields)
        flash("策展作品已更新。", "success")
    except GalleryAdminError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("admin.gallery"))


@admin_bp.route("/gallery/curated/<string:image_id>/delete", methods=["POST"])
@login_required
@admin_required
def gallery_curated_delete(image_id: str):
    try:
        gallery_delete_curated_image(current_user.id, image_id)
        flash("策展作品已从画廊下线（对象存储将在保留期后回收）。", "success")
    except GalleryAdminError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("admin.gallery"))


def _curated_upload_limit_mb() -> int:
    configured = int(current_app.config.get("MAX_UPLOAD_MB", CURATED_MAX_FILE_MB) or CURATED_MAX_FILE_MB)
    return max(1, min(configured, CURATED_MAX_FILE_MB))


def _curated_upload_limit() -> int:
    return _curated_upload_limit_mb() * 1024 * 1024


def _matches_signature(payload: bytes, extension: str) -> bool:
    """Reject renamed files early; the Generation Service re-validates with sharp."""
    if extension in {"jpg", "jpeg"}:
        return payload[:3] == b"\xff\xd8\xff"
    if extension == "png":
        return payload[:8] == b"\x89PNG\r\n\x1a\n"
    if extension == "webp":
        return payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"
    return False


def _localized_curated(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "publishedAtLocal": localize_iso(item.get("publishedAt")),
            "createdAtLocal": localize_iso(item.get("createdAt")),
        }
        for item in items
    ]


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
