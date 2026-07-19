"""Vercel Serverless entry point for the Flask application.

Vercel auto-detects Flask from a top-level ``app`` instance in:
  - api/index.py
  - app.py, index.py, main.py at project root, etc.

The ``app`` object here is imported from the main ``app.py`` module (parent dir).
When the Vercel build process adds ``api/index.py`` to the PYTHONPATH, importing
``app.py`` triggers the module-level ``app = create_app()`` — which reads the
``VERCEL`` env var and applies Serverless adaptions automatically.
"""

import sys
from pathlib import Path

# Ensure the project root is importable (so ``from app import app`` works).
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from app import app  # noqa: E402, F401  — the WSGI instance Vercel looks for
