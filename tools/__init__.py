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

import yaml
from flask import Flask

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
        for entry in _load_yaml_config(app):
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
            tool.order = int(entry.get("order", 100))
            tool.category = entry.get("category", "other") or "other"
            if "enabled" in entry:
                tool.enabled = bool(entry["enabled"])
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
    registered: set[str] = set()
    failed: dict[str, str] = {}  # tid -> error message (for /diag)

    # Now register based on the YAML config.
    for entry in entries:
        tid = entry["id"]
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
    return (
        db.session.query(Tool)
        .filter_by(enabled=True)
        .order_by(Tool.order.asc(), Tool.name.asc())
        .all()
    )


def list_all_tools() -> list[Tool]:
    return db.session.query(Tool).order_by(Tool.order.asc()).all()
