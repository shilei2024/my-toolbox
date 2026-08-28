"""Provider-neutral notification outbox claiming and delivery adapters."""
from __future__ import annotations

import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from flask import current_app
from sqlalchemy import select, update

from extensions import db
from shared.models import NotificationDelivery, NotificationOutbox, NotificationWorkerHeartbeat


class NotificationAdapterError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def cancel_pending_notifications(module_code: str, object_type: str, object_id: str) -> int:
    result = db.session.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.module_code == module_code,
            NotificationOutbox.object_type == object_type,
            NotificationOutbox.object_id == object_id,
            NotificationOutbox.status.in_(("pending", "failed")),
        )
        .values(status="cancelled", claim_token=None, claimed_at=None, updated_at=datetime.now(timezone.utc))
    )
    return int(result.rowcount or 0)


def cancel_pending_notifications_for_organization(
    module_code: str, organization_id: str
) -> int:
    """Cancel unsent intents when organization-wide scheduling policy changes."""
    result = db.session.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.module_code == module_code,
            NotificationOutbox.organization_id == organization_id,
            NotificationOutbox.status.in_(("pending", "failed")),
        )
        .values(
            status="cancelled",
            claim_token=None,
            claimed_at=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    return int(result.rowcount or 0)


def _render_message(outbox: NotificationOutbox) -> tuple[str, str]:
    data = outbox.template_data
    subject = f"[客户项目提醒] {data.get('project_code', '')} {data.get('project_name', '')}".strip()
    subject = subject.replace("\r", " ").replace("\n", " ")
    body = "\n".join(
        (
            f"提醒类型：{data.get('reminder_label', outbox.event_type)}",
            f"客户：{data.get('customer_name', '—')}",
            f"项目：{data.get('project_code', '')} {data.get('project_name', '')}",
            f"阶段：{data.get('stage_code', '—')}",
            f"下一步：{data.get('next_action', '—')}",
            f"跟进时间：{data.get('next_follow_up_at', '—')}",
            f"最近有效更新：{data.get('last_meaningful_update_at', '—')}",
            f"查看项目：{data.get('project_url', '')}",
            "",
            "此邮件由客户项目提醒服务生成，项目详情需登录后查看。",
        )
    )
    return subject[:255], body


def _deliver(outbox: NotificationOutbox, delivery: NotificationDelivery) -> str:
    adapter = str(current_app.config.get("NOTIFICATION_ADAPTER", "dry-run")).strip().lower()
    if adapter == "dry-run":
        return f"dry-run:{uuid.uuid4()}"
    if adapter != "smtp":
        raise NotificationAdapterError("ADAPTER_NOT_SUPPORTED")
    if not current_app.config.get("CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED", False):
        raise NotificationAdapterError("LIVE_DELIVERY_DISABLED")
    host = str(current_app.config.get("SMTP_HOST", "")).strip()
    sender = str(current_app.config.get("SMTP_FROM", "")).strip()
    if not host or not sender:
        raise NotificationAdapterError("SMTP_NOT_CONFIGURED")
    mode = str(current_app.config.get("SMTP_SECURITY", "starttls")).lower()
    if mode not in {"starttls", "ssl"}:
        raise NotificationAdapterError("SMTP_SECURITY_INVALID")
    if any(char in sender + delivery.recipient_address for char in ("\r", "\n")):
        raise NotificationAdapterError("INVALID_MAIL_ADDRESS")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = delivery.recipient_address
    message["Subject"], body = _render_message(outbox)
    message.set_content(body)
    port = int(current_app.config.get("SMTP_PORT", 587))
    timeout = int(current_app.config.get("SMTP_TIMEOUT_SECONDS", 10))
    try:
        client_cls = smtplib.SMTP_SSL if mode == "ssl" else smtplib.SMTP
        with client_cls(host, port, timeout=timeout) as client:
            if mode == "starttls":
                client.starttls(context=ssl.create_default_context())
            username = str(current_app.config.get("SMTP_USERNAME", ""))
            password = str(current_app.config.get("SMTP_PASSWORD", ""))
            if username:
                client.login(username, password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        raise NotificationAdapterError("SMTP_DELIVERY_FAILED") from exc
    return f"smtp:{uuid.uuid4()}"


def dispatch_due_notifications(now: datetime | None = None, limit: int = 100) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    heartbeat = db.session.get(NotificationWorkerHeartbeat, "notification-dispatch")
    if heartbeat is None:
        heartbeat = NotificationWorkerHeartbeat(worker_name="notification-dispatch")
        db.session.add(heartbeat)
    heartbeat.status = "running"
    heartbeat.last_started_at = now
    db.session.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.status == "processing",
            NotificationOutbox.claimed_at < now - timedelta(minutes=5),
        )
        .values(
            status="failed",
            next_attempt_at=now,
            claim_token=None,
            claimed_at=None,
            last_error_code="STALE_CLAIM_RECOVERED",
            updated_at=now,
        )
    )
    db.session.commit()

    statement = (
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status.in_(("pending", "failed")),
            NotificationOutbox.next_attempt_at <= now,
            NotificationOutbox.scheduled_for <= now,
        )
        .order_by(NotificationOutbox.scheduled_for, NotificationOutbox.id)
        .limit(max(1, min(limit, 500)))
        .with_for_update(skip_locked=True)
    )
    rows = list(db.session.scalars(statement))
    claim_token = str(uuid.uuid4())
    for row in rows:
        row.status = "processing"
        row.claim_token = claim_token
        row.claimed_at = now
    db.session.commit()

    sent = failed = 0
    for row_id in [row.id for row in rows]:
        outbox = db.session.get(NotificationOutbox, row_id)
        if outbox is None or outbox.claim_token != claim_token:
            continue
        deliveries = list(
            db.session.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.outbox_id == outbox.id,
                    NotificationDelivery.status != "sent",
                )
            )
        )
        error_code = None
        provider_ids: list[str] = []
        for delivery in deliveries:
            try:
                provider_id = _deliver(outbox, delivery)
                provider_ids.append(provider_id)
                delivery.status = "sent"
                delivery.sent_at = now
                delivery.provider_message_id = provider_id
                delivery.last_error_code = None
                delivery.attempts += 1
            except NotificationAdapterError as exc:
                error_code = exc.code
                delivery.status = "failed"
                delivery.last_error_code = exc.code
                delivery.attempts += 1
        outbox.attempts += 1
        outbox.claim_token = None
        outbox.claimed_at = None
        if error_code is None:
            outbox.status = "sent"
            outbox.sent_at = now
            outbox.provider_message_id = ",".join(provider_ids)[:255] or None
            outbox.last_error_code = None
            sent += 1
        else:
            outbox.last_error_code = error_code
            outbox.status = "dead" if outbox.attempts >= outbox.max_attempts else "failed"
            outbox.next_attempt_at = now + timedelta(minutes=min(60, 2 ** outbox.attempts))
            failed += 1
        db.session.commit()

    heartbeat = db.session.get(NotificationWorkerHeartbeat, "notification-dispatch")
    heartbeat.status = "ok" if failed == 0 else "degraded"
    heartbeat.last_completed_at = datetime.now(timezone.utc)
    heartbeat.processed_count = len(rows)
    heartbeat.failed_count = failed
    heartbeat.last_error_code = "DELIVERY_FAILURES" if failed else None
    db.session.commit()
    return {"claimed": len(rows), "sent": sent, "failed": failed}
