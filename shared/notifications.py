"""Provider-neutral notification outbox claiming and delivery adapters."""
from __future__ import annotations

import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr

from flask import current_app
from sqlalchemy import select, update

from extensions import db
from shared.models import NotificationDelivery, NotificationOutbox, NotificationWorkerHeartbeat


class NotificationAdapterError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def notification_readiness(*, require_live: bool = False) -> dict[str, object]:
    """Return a secret-free readiness report for operators and systemd preflight."""
    adapter = str(current_app.config.get("NOTIFICATION_ADAPTER", "dry-run")).strip().lower()
    issues: list[str] = []
    if adapter not in {"dry-run", "smtp"}:
        issues.append("NOTIFICATION_ADAPTER must be dry-run or smtp")
    if require_live and adapter != "smtp":
        issues.append("NOTIFICATION_ADAPTER must be smtp for live delivery")
    if adapter == "smtp" or require_live:
        if not current_app.config.get("CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED", False):
            issues.append("CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=false")
        if not str(current_app.config.get("SMTP_HOST", "")).strip():
            issues.append("SMTP_HOST is empty")
        sender = str(current_app.config.get("SMTP_FROM", "")).strip()
        if not _valid_mail_address(sender):
            issues.append("SMTP_FROM is invalid")
        if str(current_app.config.get("SMTP_SECURITY", "starttls")).lower() not in {"starttls", "ssl"}:
            issues.append("SMTP_SECURITY must be starttls or ssl")
        username = str(current_app.config.get("SMTP_USERNAME", ""))
        password = str(current_app.config.get("SMTP_PASSWORD", ""))
        if bool(username) != bool(password):
            issues.append("SMTP_USERNAME and SMTP_PASSWORD must be configured together")
        try:
            if int(current_app.config.get("SMTP_PORT", 0)) not in range(1, 65536):
                raise ValueError
            if int(current_app.config.get("SMTP_TIMEOUT_SECONDS", 0)) not in range(1, 121):
                raise ValueError
        except (TypeError, ValueError):
            issues.append("SMTP_PORT or SMTP_TIMEOUT_SECONDS is invalid")
    base_url = str(current_app.config.get("APP_BASE_URL", "")).strip()
    if (adapter == "smtp" or require_live) and not base_url.startswith("https://"):
        issues.append("APP_BASE_URL must be the public HTTPS site URL")
    return {"ready": not issues, "adapter": adapter, "issues": issues}


def _valid_mail_address(value: str) -> bool:
    if not value or any(char in value for char in ("\r", "\n")):
        return False
    address = parseaddr(value)[1]
    return bool(address and "@" in address and address.rsplit("@", 1)[1])


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


def _smtp_send(recipient: str, subject: str, body: str) -> None:
    host = str(current_app.config.get("SMTP_HOST", "")).strip()
    sender = str(current_app.config.get("SMTP_FROM", "")).strip()
    if not host or not sender:
        raise NotificationAdapterError("SMTP_NOT_CONFIGURED")
    mode = str(current_app.config.get("SMTP_SECURITY", "starttls")).lower()
    if mode not in {"starttls", "ssl"}:
        raise NotificationAdapterError("SMTP_SECURITY_INVALID")
    if not _valid_mail_address(sender) or not _valid_mail_address(recipient):
        raise NotificationAdapterError("INVALID_MAIL_ADDRESS")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    port = int(current_app.config.get("SMTP_PORT", 587))
    timeout = int(current_app.config.get("SMTP_TIMEOUT_SECONDS", 10))
    try:
        client_cls = smtplib.SMTP_SSL if mode == "ssl" else smtplib.SMTP
        with client_cls(host, port, timeout=timeout) as client:
            if mode == "starttls":
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            username = str(current_app.config.get("SMTP_USERNAME", ""))
            password = str(current_app.config.get("SMTP_PASSWORD", ""))
            if bool(username) != bool(password):
                raise NotificationAdapterError("SMTP_CREDENTIALS_INCOMPLETE")
            if username and password:
                client.login(username, password)
            client.send_message(message)
    except NotificationAdapterError:
        raise
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        raise NotificationAdapterError("SMTP_DELIVERY_FAILED") from exc


def send_test_email(recipient: str) -> None:
    """Send an operator-requested message through the exact production SMTP path."""
    readiness = notification_readiness(require_live=True)
    if not readiness["ready"]:
        raise NotificationAdapterError("NOTIFICATION_NOT_READY")
    if not _valid_mail_address(recipient):
        raise NotificationAdapterError("INVALID_MAIL_ADDRESS")
    _smtp_send(
        recipient,
        "[客户项目提醒] SMTP 配置测试",
        "客户项目提醒服务已成功连接 SMTP 并发送此测试邮件。\n\n此邮件不包含客户或项目数据。",
    )


def _deliver(outbox: NotificationOutbox, delivery: NotificationDelivery) -> str:
    adapter = str(current_app.config.get("NOTIFICATION_ADAPTER", "dry-run")).strip().lower()
    if adapter == "dry-run":
        return f"dry-run:{uuid.uuid4()}"
    if adapter != "smtp":
        raise NotificationAdapterError("ADAPTER_NOT_SUPPORTED")
    if not current_app.config.get("CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED", False):
        raise NotificationAdapterError("LIVE_DELIVERY_DISABLED")
    subject, body = _render_message(outbox)
    _smtp_send(delivery.recipient_address, subject, body)
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
