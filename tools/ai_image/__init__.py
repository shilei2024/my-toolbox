"""
AI image generation tool.

`generate_image` is intentionally a thin wrapper around a pluggable provider,
so swapping DALL·E / SiliconFlow / a local Stable Diffusion endpoint is just
a matter of dropping a new class in `ai_image/providers.py`.

The route is async-poll: the form posts, we kick off a job and return a
`task_id`; the client polls until done. For mock / dev no actual queue is
needed, so we do it inline.
"""
from __future__ import annotations

import base64
import io
import logging
import time
import uuid
from typing import Any, Callable

import requests
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    render_template,
    request,
    url_for,
)

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, safe_filename

logger = logging.getLogger(__name__)
tool_bp = Blueprint("ai_image", __name__)


# ---- in-memory task store; for production scale this becomes Redis/DB ----
_TASKS: dict[str, dict[str, Any]] = {}


# -----------------------------------------------------------------------------
# Provider abstraction
# -----------------------------------------------------------------------------
class ImageProvider:
    name = "base"

    def generate(self, prompt: str, size: str, api_key: str, base_url: str, model: str) -> bytes:  # noqa: D401
        raise NotImplementedError


class OpenAIProvider(ImageProvider):
    """OpenAI / OpenAI-compatible image endpoint (gpt-image-1, dall-e-3, etc.)."""

    name = "openai"

    # OpenAI only accepts a fixed set of sizes depending on the model.
    # Map our free-form "WxH" to the closest supported one.
    _GPT_IMAGE_SIZES = ["1024x1024", "1536x1024", "1024x1536", "auto"]
    _DALLE3_SIZES = ["1024x1024", "1792x1024", "1024x1792"]

    def _nearest_size(self, size: str, model: str) -> str:
        try:
            w, h = size.lower().split("x", 1)
            w, h = int(w), int(h)
        except (ValueError, AttributeError):
            return "1024x1024"
        candidates = self._DALLE3_SIZES if "dall-e" in (model or "").lower() else self._GPT_IMAGE_SIZES[:-1]
        best = min(candidates, key=lambda s: abs(int(s.split("x")[0]) - w) + abs(int(s.split("x")[1]) - h))
        return best

    def generate(self, prompt: str, size: str, api_key: str, base_url: str, model: str) -> bytes:
        if not api_key:
            raise RuntimeError("未配置 AI_API_KEY")
        url = f"{base_url.rstrip('/')}/images/generations"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        actual_size = self._nearest_size(size, model)
        payload = {
            "model": model or "gpt-image-1",
            "prompt": prompt,
            "size": actual_size,
            "n": 1,
        }
        if "dall-e" in (model or "").lower():
            payload["response_format"] = "b64_json"

        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        if resp.status_code >= 400:
            raise RuntimeError(f"AI provider {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        try:
            b64 = data["data"][0]["b64_json"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"AI 返回格式异常: {data}") from exc
        return base64.b64decode(b64)


class SiliconFlowProvider(OpenAIProvider):
    """OpenAI-compatible SiliconFlow endpoint."""

    name = "siliconflow"


class PollinationsProvider(ImageProvider):
    """Pollinations.ai — free, no API key required.

    Hit a simple GET endpoint that streams back a JPEG:
        https://image.pollinations.ai/prompt/<urlencoded prompt>?width=...&height=...&nologo=true

    Great as a zero-config default so the tool works out of the box.
    """

    name = "pollinations"
    DEFAULT_BASE_URL = "https://image.pollinations.ai"

    def generate(self, prompt: str, size: str, api_key: str, base_url: str, model: str) -> bytes:
        from urllib.parse import quote

        base = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        # Parse "WxH" → width / height; Pollinations accepts arbitrary sizes.
        try:
            w, h = size.lower().split("x")
            width = int(w)
            height = int(h)
        except (ValueError, AttributeError):
            width = height = 1024

        # Cap to Pollinations' sane max to avoid huge downloads.
        width = max(64, min(width, 4096))
        height = max(64, min(height, 4096))

        url = (
            f"{base}/prompt/{quote(prompt, safe='')}"
            f"?width={width}&height={height}&nologo=true"
        )
        # model param is optional on Pollinations (flux / turbo). If the
        # admin set a model, forward it.
        if model and model not in {"", "default", "pollinations"}:
            url += f"&model={quote(model)}"

        resp = requests.get(url, timeout=120)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Pollinations {resp.status_code}: {resp.text[:200]}"
            )
        if len(resp.content) < 100:
            raise RuntimeError("Pollinations 返回的图片为空，请稍后再试。")
        return resp.content


class MockProvider(ImageProvider):
    """Generate a visible placeholder PNG so the UI works without any key.

    Draws a labelled gray rectangle with Pillow so the user sees something
    real instead of a 1x1 transparent pixel.
    """

    name = "mock"

    def generate(self, prompt: str, size: str, api_key: str, base_url: str, model: str) -> bytes:
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

        try:
            w, h = size.lower().split("x")
            width, height = int(w), int(h)
        except (ValueError, AttributeError):
            width = height = 512
        width = max(256, min(width, 4096))
        height = max(256, min(height, 4096))

        img = Image.new("RGB", (width, height), (90, 90, 110))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 24)
        except Exception:  # noqa: BLE001
            font = ImageFont.load_default()
        label = "AI 作图 (Mock)\n未配置真实 API"
        draw.text((width // 2, height // 2), label, fill=(255, 255, 255), anchor="mm", font=font)
        # Truncate the prompt and show it under the label.
        snippet = (prompt[:60] + "…") if len(prompt) > 60 else prompt
        draw.text((width // 2, height // 2 + 40), snippet, fill=(200, 200, 220), anchor="mm", font=font)
        out = io.BytesIO()
        img.save(out, format="PNG")
        out.seek(0)
        return out.getvalue()


_PROVIDERS: dict[str, Callable[[], ImageProvider]] = {
    "openai": OpenAIProvider,
    "siliconflow": SiliconFlowProvider,
    "pollinations": PollinationsProvider,
    "mock": MockProvider,
}


def _provider() -> ImageProvider:
    name = _get_ai_config("AI_PROVIDER", current_app.config.get("AI_PROVIDER", "pollinations"))
    factory = _PROVIDERS.get(name, PollinationsProvider)
    return factory()


def _get_ai_config(key: str, fallback: str = "") -> str:
    """Read an AI setting from the DB (admin-configurable) with a fallback
    to the app config / env. Returns empty string if unset everywhere."""
    from models import Setting  # noqa: PLC0415

    row = db.session.get(Setting, key)
    if row and row.value:
        return row.value
    return fallback or ""


# We need `db` here — import lazily to avoid a circular import at module load.
from extensions import db  # noqa: E402


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "ai_image",
            "name": "AI 作图",
            "icon": "bi-brush",
            "color": "#d63384",
        },
        remaining=remaining_for("ai_image"),
        body_template="tools/ai_image/_body.html",
        tool_js_list=["js/tools.js"],
    )


@tool_bp.post("/generate")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("ai_image")
def generate():
    prompt = (request.form.get("prompt") or "").strip()
    size = request.form.get("size", "1024x1024")
    if not prompt:
        return jsonify(error="提示词不能为空"), 400
    if len(prompt) > 2000:
        return jsonify(error="提示词太长（最多 2000 字）"), 400

    # Parse "WxH" and clamp to a sane range. Old code only allowed three
    # fixed sizes; we now accept any WxH so the new ratio × resolution UI
    # can produce e.g. 1920x1080, 1280x720, 3840x2160, etc.
    try:
        w_str, h_str = size.lower().split("x", 1)
        width = int(w_str)
        height = int(h_str)
    except (ValueError, AttributeError):
        width = height = 1024
    # Clamp each side to [64, 4096] — Pollinations / OpenAI both reject
    # anything bigger, and anything below 64 is pointless.
    width = max(64, min(width, 4096))
    height = max(64, min(height, 4096))
    size = f"{width}x{height}"

    task_id = uuid.uuid4().hex
    _TASKS[task_id] = {"status": "pending", "ts": time.time(), "error": None}
    started_at = time.time()
    # Read AI config from DB (admin-configurable) with env fallback.
    api_key = _get_ai_config("AI_API_KEY", current_app.config.get("AI_API_KEY", ""))
    base_url = _get_ai_config("AI_BASE_URL", current_app.config.get("AI_BASE_URL", ""))
    model = _get_ai_config("AI_MODEL", current_app.config.get("AI_MODEL", ""))
    try:
        image_bytes = _provider().generate(
            prompt=prompt,
            size=size,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        filename = safe_filename("ai_image.png")
        out_path = current_app.config["UPLOAD_DIR"] / filename
        out_path.write_bytes(image_bytes)

        # Try to read dimensions (best-effort; Pillow may not be installed in some envs)
        width = height = None
        try:
            from PIL import Image  # noqa: PLC0415
            with Image.open(out_path) as img:
                width, height = img.size
        except Exception as exc:  # noqa: BLE001
            logger.debug("ai_image: could not read dimensions: %s", exc)

        _TASKS[task_id] = {
            "status": "done",
            "ts": time.time(),
            "url": url_for("ai_image.download", filename=filename),
            "filename": filename,
            "size": len(image_bytes),
            "mime": "image/png",
            "width": width,
            "height": height,
            "duration_seconds": round(time.time() - started_at, 2),
            "prompt": prompt,
            "model": model or _provider().name,
        }
        commit_usage("ai_image", success=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_image generate failed: %s", exc)
        _TASKS[task_id] = {"status": "failed", "ts": time.time(), "error": str(exc)}
        commit_usage("ai_image", success=False, message=str(exc))

    # prune memory
    cutoff = time.time() - 3600
    for tid in list(_TASKS.keys()):
        if _TASKS[tid]["ts"] < cutoff:
            _TASKS.pop(tid, None)

    return jsonify(task_id=task_id)


@tool_bp.get("/status/<task_id>")
def status(task_id: str):
    task = _TASKS.get(task_id)
    if task is None:
        return jsonify(error="任务不存在或已过期"), 404
    return jsonify(task)


@tool_bp.get("/download/<path:filename>")
def download(filename: str):
    from flask import abort, send_from_directory

    if not is_allowed_ext(filename, {"png", "jpg", "jpeg", "webp", "gif"}):
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"],
        filename,
        as_attachment=True,
    )
