"""Generic helpers used across blueprints."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from flask import current_app, has_request_context, session
from werkzeug.utils import secure_filename

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
CHINA_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
DOWNLOAD_SESSION_KEY = "issued_downloads"
DOWNLOAD_SESSION_LIMIT = 24
DOWNLOAD_TTL_SECONDS = 60 * 30


def safe_filename(original: str) -> str:
    """Create an unguessable, session-bound filename for a staged download."""
    base = secure_filename(original) or "file"
    base = SAFE_FILENAME_RE.sub("_", base)
    filename = f"{uuid.uuid4().hex}_{base[:120]}"
    bind_download_to_session(filename)
    return filename


def bind_download_to_session(filename: str) -> None:
    """Authorize a staged result for the current browser session for a short time.

    Tool outputs live in the shared upload directory.  A high-entropy filename is
    useful defense in depth, but it must not be the access-control mechanism.
    Keeping a small, expiring allow-list in Flask's signed session makes a copied
    result URL unusable from another browser without introducing a new database
    table for ephemeral artifacts.
    """
    if not filename or not has_request_context():
        return
    now = int(datetime.now(timezone.utc).timestamp())
    previous = session.get(DOWNLOAD_SESSION_KEY, {})
    allowed = {
        name: expires_at
        for name, expires_at in previous.items()
        if isinstance(name, str) and isinstance(expires_at, int) and expires_at > now
    }
    allowed[filename] = now + DOWNLOAD_TTL_SECONDS
    if len(allowed) > DOWNLOAD_SESSION_LIMIT:
        allowed = dict(sorted(allowed.items(), key=lambda item: item[1], reverse=True)[:DOWNLOAD_SESSION_LIMIT])
    session[DOWNLOAD_SESSION_KEY] = allowed
    session.modified = True


def current_session_can_download(filename: str) -> bool:
    """Return whether ``filename`` was issued to this browser session."""
    if not has_request_context():
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    allowed = session.get(DOWNLOAD_SESSION_KEY, {})
    expires_at = allowed.get(filename) if isinstance(allowed, dict) else None
    return isinstance(expires_at, int) and expires_at > now


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def china_now() -> datetime:
    """Return the current time in China Standard Time (UTC+8)."""
    return datetime.now(CHINA_TIMEZONE)


def china_today_str() -> str:
    """Return today's calendar date in China, used by daily quotas."""
    return china_now().strftime("%Y-%m-%d")


def to_china_time(value: Optional[datetime]) -> Optional[datetime]:
    """Convert a DB datetime to China time; naive DB values are treated as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(CHINA_TIMEZONE)


def china_day_utc_bounds(day: str | date) -> tuple[datetime, datetime]:
    """Return the half-open UTC range for one China calendar day."""
    parsed = date.fromisoformat(day) if isinstance(day, str) else day
    start_china = datetime.combine(parsed, time.min, tzinfo=CHINA_TIMEZONE)
    end_china = start_china + timedelta(days=1)
    return (
        start_china.astimezone(timezone.utc).replace(tzinfo=None),
        end_china.astimezone(timezone.utc).replace(tzinfo=None),
    )


def get_client_ip() -> str:
    """Return the best-guess client IP.

    When PROXY_FIX_COUNT is configured (app behind Nginx/Cloudflare),
    werkzeug's ProxyFix already rewrote request.remote_addr from the trusted
    X-Forwarded-For chain, so we trust remote_addr alone and never read the
    header directly — otherwise a direct client could spoof X-Forwarded-For to
    fake its IP. Without ProxyFix, remote_addr is the socket peer (the proxy),
    which is the honest value we can compute.
    """
    from flask import request

    return request.remote_addr or "0.0.0.0"


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def anon_fingerprint(anon_id: str, ip: str, ua: str) -> str:
    """Stable fingerprint tying an anon session to a UA. Helps catch multi-tab abuse."""
    return short_hash(f"{anon_id}|{ip}|{ua}")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_download_path(upload_dir: Path, filename: str) -> Optional[Path]:
    """Return a traversal-safe absolute path under ``upload_dir`` for ``filename``.

    Unlike :func:`safe_filename`, this does **not** rename the file — it preserves
    the exact stored name so a download route can find the file that was saved
    earlier. Returns ``None`` if the filename is empty, contains path separators
    / parent traversal, or resolves outside ``upload_dir``.
    """
    if not filename or not current_session_can_download(filename):
        return None
    if "/" in filename or "\\" in filename or ".." in filename:
        return None
    base = Path(upload_dir).resolve()
    try:
        target = (base / filename).resolve()
        target.relative_to(base)
    except (ValueError, OSError):
        return None
    return target


def stage_download(suggested_name: str, data: bytes) -> str:
    """Persist a session-authorized result under the configured upload root.

    Callers must obtain ``suggested_name`` from :func:`safe_filename` first;
    this helper intentionally rejects path components instead of silently
    rewriting a stored filename.
    """
    if (
        not suggested_name
        or suggested_name in {".", ".."}
        or Path(suggested_name).name != suggested_name
    ):
        raise ValueError("Invalid staged download filename")
    upload_dir = ensure_dir(Path(current_app.config["UPLOAD_DIR"]))
    target = upload_dir / suggested_name
    try:
        target.resolve().relative_to(upload_dir.resolve())
    except ValueError as exc:
        raise ValueError("Invalid staged download filename") from exc
    target.write_bytes(data)
    return suggested_name


def human_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def is_allowed_ext(filename: str, allowed: set[str]) -> bool:
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[-1].lower() in allowed


def parse_page_ranges(spec: str, total_pages: int) -> list[int]:
    """Parse `1-3,5,7-9` into a sorted, de-duplicated list of 1-indexed page numbers.

    Raises ValueError with a human-readable message on invalid input.
    """
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("页码范围不能为空")

    out: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            try:
                a, b = chunk.split("-", 1)
                start = int(a.strip())
                end = int(b.strip())
            except ValueError:
                raise ValueError(f"无法解析区间 “{chunk}”") from None
            if start > end:
                start, end = end, start
            for n in range(start, end + 1):
                if 1 <= n <= total_pages:
                    out.add(n)
        else:
            try:
                n = int(chunk)
            except ValueError:
                raise ValueError(f"无法解析页码 “{chunk}”") from None
            if 1 <= n <= total_pages:
                out.add(n)

    if not out:
        raise ValueError("指定的页码范围没有任何有效页面")

    return sorted(out)


def format_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    local = to_china_time(dt)
    return local.strftime("%Y-%m-%d %H:%M:%S") if local else "—"


def get_or_create_setting(key: str, default: str = "") -> str:
    from extensions import db
    from models import Setting

    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=default)
        db.session.add(row)
        db.session.commit()
    return row.value or default
