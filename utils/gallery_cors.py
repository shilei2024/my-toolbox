"""Gallery cross-origin (CORS) helpers for the Flask main site.

The Gallery Web (Next.js) performs a cross-origin prefetch of the Flask
login/logout pages. This module emits CORS headers only for the configured
Gallery origin and answers the OPTIONS preflight, without ever using a
wildcard origin.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from flask import Flask, make_response, request


def trusted_origins(external_url: str) -> set[str]:
    """Derive the exact trusted origin from AI_IMAGE_EXTERNAL_URL."""
    if not external_url:
        return set()
    try:
        parsed = urlparse(external_url)
    except ValueError:
        return set()
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        return set()
    return {f"{parsed.scheme}://{parsed.netloc}".rstrip("/")}


def gallery_cors_origins(app: Flask) -> set[str]:
    """Trusted origins allowed to call the Flask site cross-site.

    The configured AI Gallery origin plus any explicit GALLERY_CORS_ORIGINS
    entries (comma-separated). Unconfigured deployments get no CORS headers.
    """
    origins = trusted_origins(app.config.get("AI_IMAGE_EXTERNAL_URL", ""))
    for raw in os.environ.get("GALLERY_CORS_ORIGINS", "").split(","):
        value = raw.strip().rstrip("/")
        if value:
            origins.add(value)
    return origins


def apply_gallery_cors(app: Flask) -> None:
    """Allow the Gallery Web to navigate to /login, /logout and /register.

    The Next.js client prefetches the Flask login page cross-origin, so Flask
    must answer the OPTIONS preflight and echo CORS headers with credentials
    for that exact origin.
    """
    cors_origins = gallery_cors_origins(app)

    @app.before_request
    def _gallery_cors_preflight():
        origin = request.headers.get("Origin")
        if request.method == "OPTIONS" and origin and origin.rstrip("/") in cors_origins:
            response = make_response("", 204)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = request.headers.get(
                "Access-Control-Request-Headers", "Content-Type, X-CSRFToken, Accept"
            )
            response.headers["Access-Control-Max-Age"] = "600"
            response.headers["Vary"] = "Origin, Access-Control-Request-Headers, Access-Control-Request-Method"
            return response
        return None

    @app.after_request
    def _gallery_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") in cors_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
        return response
