"""
Vercel WSGI entry point.

Vercel auto-detects Flask from a top-level ``app`` instance in:
    app.py, wsgi.py, index.py, main.py, api/index.py

This file just re-exports the ``app`` object from ``app.py``.
All Vercel-specific adaptation logic and debug logging lives inside
``app.py:create_app()``.
"""
import sys
import traceback

print("[wsgi.py] importing app from app.py …", file=sys.stderr, flush=True)

try:
    from app import app  # noqa: E402, F401
    print("[wsgi.py] ✓ app imported successfully", file=sys.stderr, flush=True)
except Exception:
    print("[wsgi.py] ✗ FATAL — failed to import app:", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    raise

# Vercel looks for ``app`` at module level
