"""Generic helpers used across blueprints."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import current_app
from werkzeug.utils import secure_filename

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(original: str) -> str:
    """Sanitize a user-provided filename, then add a short uuid prefix to avoid collisions."""
    base = secure_filename(original) or "file"
    base = SAFE_FILENAME_RE.sub("_", base)
    return f"{uuid.uuid4().hex[:8]}_{base[:120]}"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_client_ip() -> str:
    """Return the best-guess client IP, respecting X-Forwarded-For if behind a proxy."""
    from flask import request

    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def anon_fingerprint(anon_id: str, ip: str, ua: str) -> str:
    """Stable fingerprint tying an anon session to a UA. Helps catch multi-tab abuse."""
    return short_hash(f"{anon_id}|{ip}|{ua}")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


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
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_or_create_setting(key: str, default: str = "") -> str:
    from extensions import db
    from models import Setting

    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=default)
        db.session.add(row)
        db.session.commit()
    return row.value or default
