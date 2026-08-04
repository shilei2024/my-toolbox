"""Safe, read-only validation for the Flask-to-Gallery production bridge."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from flask import Flask


@dataclass(frozen=True)
class IntegrationCheck:
    name: str
    ok: bool
    message: str


def gallery_integration_checks(app: Flask) -> list[IntegrationCheck]:
    gallery = _url(str(app.config.get("AI_IMAGE_EXTERNAL_URL", "")))
    toolbox = _url(str(app.config.get("APP_BASE_URL", "")))
    secret = str(app.config.get("GALLERY_INTROSPECTION_SECRET", ""))
    cookie_domain = str(app.config.get("SESSION_COOKIE_DOMAIN") or "").lstrip(".").lower()
    service_url = _url(str(app.config.get("GALLERY_SERVICE_BASE_URL", "")))
    hmac_secret = str(app.config.get("GALLERY_INTERNAL_HMAC_SECRET", ""))
    production_https = bool(gallery and gallery.scheme == "https")

    checks = [
        IntegrationCheck("gallery_url", bool(gallery and _safe_web_url(gallery)), "AI_IMAGE_EXTERNAL_URL must be an absolute HTTPS URL (HTTP is allowed only on loopback)"),
        IntegrationCheck("app_base_url", bool(toolbox and _safe_web_url(toolbox)), "APP_BASE_URL must be an absolute HTTPS URL (HTTP is allowed only on loopback)"),
        IntegrationCheck("introspection_secret", len(secret.encode("utf-8")) >= 32, "GALLERY_INTROSPECTION_SECRET must contain at least 32 UTF-8 bytes"),
        IntegrationCheck("gallery_service_url", bool(service_url and _safe_web_url(service_url)), "GALLERY_SERVICE_BASE_URL must be an absolute HTTPS URL (HTTP is allowed only on loopback)"),
        IntegrationCheck("gallery_hmac_secret", len(hmac_secret.encode("utf-8")) >= 32, "GALLERY_INTERNAL_HMAC_SECRET must contain at least 32 UTF-8 bytes"),
        IntegrationCheck("secure_cookie", not production_https or bool(app.config.get("SESSION_COOKIE_SECURE")), "SESSION_COOKIE_SECURE must be true when Gallery uses HTTPS"),
        IntegrationCheck("cookie_domain", bool(cookie_domain), "SESSION_COOKIE_DOMAIN is required so both sites receive the Flask session cookie"),
    ]
    if cookie_domain and gallery and toolbox:
        domain_ok = _under_domain(gallery.hostname, cookie_domain) and _under_domain(toolbox.hostname, cookie_domain)
        checks.append(IntegrationCheck("shared_cookie_domain", domain_ok, "APP_BASE_URL and AI_IMAGE_EXTERNAL_URL must both be under SESSION_COOKIE_DOMAIN"))
    else:
        checks.append(IntegrationCheck("shared_cookie_domain", False, "APP_BASE_URL, Gallery URL and cookie domain are all required for domain validation"))
    return checks


def _url(value: str):
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    return parsed if parsed.scheme and parsed.hostname else None


def _safe_web_url(value) -> bool:
    return value.scheme == "https" or (value.scheme == "http" and value.hostname in {"localhost", "127.0.0.1", "::1"})


def _under_domain(hostname: str | None, domain: str) -> bool:
    host = (hostname or "").lower().rstrip(".")
    return host == domain or host.endswith(f".{domain}")
