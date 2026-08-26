"""
Plugin loader — every tool lives under `tools/<id>/` and registers a
Flask Blueprint called `tool_bp`. We import them dynamically based on
`tools_config.yaml` and (re-)sync their metadata into the `tools` DB table.

To add a new tool:
  1. Create `tools/<id>/__init__.py` exposing `tool_bp`.
  2. Add an entry in `tools_config.yaml`.
  3. Restart the app.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any
from urllib.parse import urlparse

import yaml
from flask import Flask, has_request_context
from flask_login import current_user

from auth.tool_access import can_access_private_tool, register_private_tool_guards
from extensions import db
from models import Tool

logger = logging.getLogger(__name__)


def _load_yaml_config(app: Flask) -> list[dict[str, Any]]:
    path = app.config["TOOLS_CONFIG_PATH"]
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("tools", []) or []


def _import_module(module_path: str) -> Any | None:
    try:
        return importlib.import_module(module_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to import tool module %s: %s", module_path, exc)
        return None


def sync_tool_registry(app: Flask) -> None:
    """Sync the YAML registry into the DB so the admin UI sees them."""
    with app.app_context():
        entries = _load_yaml_config(app)
        for entry in entries:
            tool = db.session.get(Tool, entry["id"])
            if tool is None:
                tool = Tool(id=entry["id"])
                db.session.add(tool)
            tool.name = entry.get("name", tool.id)
            tool.description = entry.get("description", "")
            tool.icon = entry.get("icon", "bi-tools")
            tool.color = entry.get("color", "#0d6efd")
            tool.route = entry.get("route", f"/tools/{tool.id}")
            tool.blueprint_module = entry.get("blueprint_module", f"tools.{tool.id}")
            configured_external_url = entry.get("external_url", "") or ""
            if entry["id"] == "ai_image" and app.config.get("AI_IMAGE_EXTERNAL_URL"):
                configured_external_url = str(app.config["AI_IMAGE_EXTERNAL_URL"]).strip()
            parsed_external_url = urlparse(configured_external_url)
            loopback_http = parsed_external_url.scheme == "http" and parsed_external_url.hostname in {"localhost", "127.0.0.1", "::1"}
            if configured_external_url and (parsed_external_url.scheme not in {"https", "http"} or not parsed_external_url.netloc or (parsed_external_url.scheme == "http" and not loopback_http)):
                logger.error("Tool %s external URL must be an absolute HTTPS URL (HTTP allowed only on loopback); hiding entry", entry["id"])
                configured_external_url = ""
            tool.external_url = configured_external_url
            tool.order = int(entry.get("order", 100))
            tool.category = entry.get("category", "other") or "other"
            tool.required_plan = entry.get("required_plan", "free") or "free"
            if "enabled" in entry:
                tool.enabled = bool(entry["enabled"])
        if entries:
            # The YAML registry is the single source of truth: disable rows
            # that were removed from it (or never implemented) so the homepage
            # never renders a dead link to a route that does not exist.
            configured_ids = {entry["id"] for entry in entries}
            configured_routes = {entry.get("route", f"/tools/{entry['id']}") for entry in entries}
            stale = (
                db.session.query(Tool)
                .filter(
                    Tool.enabled.is_(True),
                    (Tool.id.notin_(configured_ids)) | (Tool.route.notin_(configured_routes)),
                )
                .all()
            )
            for tool in stale:
                tool.enabled = False
        db.session.commit()


def register_tools(app: Flask) -> None:
    """
    Discover and register all tool blueprints.

    `tools/<id>/` is treated as a sub-package. Anything in
    `tools_config.yaml` is imported; unknown ones are logged and skipped.

    If a tool module fails to import (e.g. a dependency is missing in the
    deploy environment), it is marked ``enabled=False`` in the DB so the
    homepage does not render a dead link to a route that doesn't exist.
    """
    # First, make sure the `tools` sub-packages themselves are importable.
    # pkgutil walks the package directory.
    import tools as _pkg  # noqa: PLC0415  (intentional self-import)

    for mod_info in pkgutil.iter_modules(_pkg.__path__):
        if mod_info.name in {"__main__"}:
            continue
        # don't actually import the tool yet — the YAML is the source of truth

    entries = _load_yaml_config(app)
    private_routes = {
        entry["id"]: entry.get("route", f"/tools/{entry['id']}")
        for entry in entries
        if entry.get("required_plan") == "private"
    }
    register_private_tool_guards(app, private_routes)
    registered: set[str] = set()
    failed: dict[str, str] = {}  # tid -> error message (for /diag)

    # Now register based on the YAML config.
    for entry in entries:
        tid = entry["id"]
        # External-link tools (e.g. AI 作图 → 独立部署的 Gallery Web) have no
        # internal blueprint; they are rendered as a link on the homepage and
        # must NOT be imported or registered here.
        if not (entry.get("blueprint_module") or "").strip():
            registered.add(tid)
            continue
        module_path = entry["blueprint_module"]
        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:  # noqa: BLE001
            failed[tid] = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:300]
            logger.error(
                "Tool %s: module %s failed to import — disabling it so the "
                "homepage doesn't show a dead link. Error: %s",
                tid, module_path, exc, exc_info=True,
            )
            continue
        bp = getattr(mod, "tool_bp", None)
        if bp is None:
            failed[tid] = "module has no `tool_bp` blueprint attribute"
            logger.error("Module %s has no `tool_bp` blueprint", module_path)
            continue
        app.register_blueprint(bp, url_prefix=entry.get("route", f"/tools/{tid}"))
        # A merged/renamed tool may keep historical URLs without creating a
        # duplicate homepage card or copying its business logic.
        for alias_index, alias in enumerate(entry.get("route_aliases", []) or []):
            if not isinstance(alias, str) or not alias.startswith("/tools/"):
                logger.warning("Tool %s: ignoring invalid route alias %r", tid, alias)
                continue
            app.register_blueprint(
                bp,
                url_prefix=alias.rstrip("/"),
                name_prefix=f"legacy_{tid}_{alias_index}",
            )
        registered.add(tid)

    # Sync enabled state: disable tools that failed to import, re-enable those
    # that registered successfully (so a previously-disabled tool comes back
    # once its dependency is fixed and redeployed).
    with app.app_context():
        changed = False
        for tid in failed:
            tool = db.session.get(Tool, tid)
            if tool is not None and tool.enabled:
                tool.enabled = False
                changed = True
        for tid in registered:
            tool = db.session.get(Tool, tid)
            if tool is not None and not tool.enabled:
                tool.enabled = True
                changed = True
        if changed:
            db.session.commit()

    # Expose diagnostics for the /diag endpoint.
    app.config["TOOL_DIAG"] = {
        "yaml_count": len(entries),
        "registered": sorted(registered),
        "failed": failed,
    }

    if failed:
        logger.warning("Tools registered %d/%d; disabled (import failed): %s",
                       len(registered), len(entries), ", ".join(sorted(failed)))
    else:
        logger.info("All %d tools registered.", len(entries))


def list_enabled_tools() -> list[Tool]:
    tools = (
        db.session.query(Tool)
        .filter_by(enabled=True)
        .order_by(Tool.order.asc(), Tool.name.asc())
        .all()
    )
    # External-link tools without a configured URL are hidden until the
    # target (e.g. the new AI 作图 / Gallery Web) is deployed and the URL is
    # filled in via tools_config.yaml. Internal tools always render.
    tools = [tool for tool in tools if tool.blueprint_module or tool.external_url]
    if not has_request_context():
        return tools
    if current_user.is_authenticated and getattr(current_user, "is_admin", False):
        return tools
    return [
        tool
        for tool in tools
        if tool.required_plan != "private" or can_access_private_tool(tool.id)
    ]


def list_all_tools() -> list[Tool]:
    return db.session.query(Tool).order_by(Tool.order.asc()).all()
