"""Ensure the unit-test suite never touches the real file-based database.

`python -m unittest discover` imports all test modules into one process. Without
this guard they would share `instance/app.db`, and every `create_app()` would
seed another admin into the same file, making assertions that assume a fresh
database (for example bootstrap admin id == 1) order-dependent and flaky.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
