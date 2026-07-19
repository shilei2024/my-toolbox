"""
Background cleanup of temp files.

We use a simple APScheduler instance started from the app factory. It runs
in-process; for a single-host 4GB box this is fine. If you scale out to
multiple workers, move this to a separate cron / worker process.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler

from extensions import db

logger = logging.getLogger(__name__)


def _sweep_uploads(upload_dir: Path, ttl_seconds: int) -> int:
    if not upload_dir.exists():
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for entry in upload_dir.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink(missing_ok=True)
                removed += 1
        except OSError as exc:  # noqa: BLE001
            logger.warning("cleanup: cannot remove %s: %s", entry, exc)
    return removed


def schedule_cleanup(app) -> BackgroundScheduler:
    """Attach a daily cleanup job to the app; return the scheduler so caller can .start()."""
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")

    @scheduler.scheduled_job("interval", minutes=15, id="sweep_uploads", coalesce=True)
    def _job() -> None:
        with app.app_context():
            removed = _sweep_uploads(
                app.config["UPLOAD_DIR"],
                app.config["TEMP_FILE_TTL_MINUTES"] * 60,
            )
            if removed:
                logger.info("cleanup: removed %d temp files", removed)

    @scheduler.scheduled_job("interval", hours=1, id="sweep_anon_pn", coalesce=True)
    def _job_anon_pn() -> None:
        """Delete anonymous PN mappings older than 24h — they're temporary."""
        with app.app_context():
            from datetime import datetime, timedelta, timezone
            from models import PnMapping
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            deleted = (
                db.session.query(PnMapping)
                .filter(PnMapping.owner_type == "anon", PnMapping.updated_at < cutoff)
                .delete(synchronize_session=False)
            )
            if deleted:
                db.session.commit()
                logger.info("cleanup: removed %d expired anon PN mappings", deleted)

    return scheduler


def manual_sweep(upload_dir: Path, ttl_seconds: int) -> int:
    return _sweep_uploads(upload_dir, ttl_seconds)
