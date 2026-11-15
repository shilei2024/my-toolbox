"""Shared TLS-only mail transport; no message or credential logging."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr
from flask import current_app

class MailError(RuntimeError):
    pass

def valid_address(value):
    if not isinstance(value, str) or any(c in value for c in ("\r", "\n")):
        return False
    address = parseaddr(value)[1]
    return bool(address and "@" in address and address.rsplit("@", 1)[1])

def send_smtp(recipient: str, subject: str, body: str) -> None:
    host = str(current_app.config.get("SMTP_HOST", "")).strip()
    sender = str(current_app.config.get("SMTP_FROM", "")).strip()
    if not host or not sender:
        raise MailError("SMTP_NOT_CONFIGURED")
    mode = str(current_app.config.get("SMTP_SECURITY", "starttls")).lower()
    if mode not in {"starttls", "ssl"}:
        raise MailError("SMTP_SECURITY_INVALID")
    if not valid_address(sender) or not valid_address(recipient):
        raise MailError("INVALID_MAIL_ADDRESS")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    port = int(current_app.config.get("SMTP_PORT", 587))
    timeout = int(current_app.config.get("SMTP_TIMEOUT_SECONDS", 10))
    try:
        client_cls = smtplib.SMTP_SSL if mode == "ssl" else smtplib.SMTP
        with client_cls(host, port, timeout=timeout, **({"context": ssl.create_default_context()} if mode == "ssl" else {})) as client:
            if mode == "starttls":
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            username = str(current_app.config.get("SMTP_USERNAME", ""))
            password = str(current_app.config.get("SMTP_PASSWORD", ""))
            if bool(username) != bool(password):
                raise MailError("SMTP_CREDENTIALS_INCOMPLETE")
            if username and password:
                client.login(username, password)
            client.send_message(message)
    except MailError:
        raise
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        raise MailError("SMTP_DELIVERY_FAILED") from None
