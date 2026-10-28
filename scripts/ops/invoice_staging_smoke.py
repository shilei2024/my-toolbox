"""One-release, in-process smoke check against the guarded restored PG database.

Run as postgres with the candidate archive as argv[1]. Never imports app/config,
opens a listener, migrates a database, or reads production environment files.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import secrets
import sys
import tempfile
from decimal import Decimal

VERIFY_DATABASE = "mytoolbox_invoice_verify_20261028_111850"
REVISION = "e4f5a6b7c8d9"


class CheckFailure(Exception):
    pass


def require(condition, label):
    if not condition:
        raise CheckFailure(label)


def historical_snapshot(db, ids=None):
    """Hash complete restored rows, including original BLOBs; never print them."""
    from sqlalchemy import text
    result = {}
    for table in ("reimbursement_invoices", "reimbursement_attachments"):
        rows = db.session.execute(text(f"SELECT id, md5(row_to_json(t)::text) FROM {table} t")).all()
        result[table] = {key: digest for key, digest in rows if ids is None or key in ids[table]}
    return result


def exercise(app):
    from extensions import db
    from models import User
    import xlrd
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    with app.app_context():
        user = User(email=f"invoice-stage-{secrets.token_hex(12)}@example.invalid", is_admin=True)
        user.set_password(secrets.token_urlsafe(32))
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    prefix = "/tools/reimbursement"

    def call(method, path, status=200, **kwargs):
        response = getattr(client, method)(prefix + path, **kwargs)
        require(response.status_code == status, f"request:{path}:expected-{status}:got-{response.status_code}")
        return response

    bootstrap = call("get", "/api/bootstrap").json
    office = bootstrap["offices"][0]["id"]
    product = bootstrap["product_lines"][0]
    period = call("post", "/api/periods", 201, json={"start_year":2026, "start_month":6,
        "end_year":2026, "end_month":7}).json["period"]["id"]

    def add_original(name, **values):
        image = io.BytesIO()
        metadata = PngInfo()
        metadata.add_text("fixture", secrets.token_hex(16))
        Image.new("RGB", (12, 12), "white").save(image, "PNG", pnginfo=metadata)
        original = image.getvalue()
        uploaded = call("post", "/upload", data={"file":(io.BytesIO(original), name)}).json
        response = call("post", "/api/invoices", 201, json={"period_id":period, "office_id":office,
            "product_line_id":product["id"], "file_url":uploaded["original_url"], "file_name":name, **values})
        return response.json["invoice"], original

    fuel, original = add_original("stage-fuel.png", document_kind="fuel", occurrence_month="2026-06")
    require(fuel["inclusion_policy"] == "retain", "fuel-policy")
    require(call("get", f"/api/summary/{period}").json["summary"]["total_amount"] == 0, "fuel-no-expense")
    bill, _ = add_original("stage-statement.png", document_kind="toll_statement", occurrence_month="2026-06",
        settlement_month="2026-07", total_amount="590.48", amount_confirmed=True, print_selected=False)
    vehicles = [{"date":day, "km_total":km, "product_line":product["name"]}
        for day, km in (("2026-06-01",10), ("2026-06-02",20), ("2026-07-01",30))]
    old = call("put", f"/api/aux/{period}", json={"vehicle":vehicles}).json
    ids = [row["id"] for row in old["aux"]["vehicle"]]
    path = f"/api/periods/{period}/toll-allocation"
    body = {"statement_id":bill["id"], "row_ids":ids[:2]}
    preview = call("post", path, json=body).json
    require(sum(Decimal(row["amount"]) for row in preview["rows"]) == Decimal("590.48"), "preview-total")
    confirm = {**body, "confirm":True, "snapshot":preview["snapshot"],
        "statement_snapshot":preview["statement_snapshot"], "amounts":["200", "390.48"]}
    call("post", path, json=confirm)
    call("post", path, 409, json=confirm)
    call("put", f"/api/aux/{period}", 409, json={**old["aux"], "_snapshot":old["aux_snapshot"]})
    summary = call("get", f"/api/summary/{period}").json
    require(Decimal(str(summary["summary"]["total_amount"])) == Decimal("650.48"), "summary-total")
    rows = summary["aux"]["vehicle"]
    require(sum(Decimal(str(row["km_total"])) for row in rows) == 60, "mileage-preserved")
    require(Decimal(str(rows[2].get("toll_fee") or 0)) == 0, "other-month-untouched")
    export = call("get", f"/api/export/details/{period}")
    sheet = xlrd.open_workbook(file_contents=export.data).sheet_by_index(1)
    require(sum(Decimal(str(sheet.cell_value(r, 7))) for r in range(4, 7)) == Decimal("590.48"), "excel-toll-total")
    require(sum(Decimal(str(sheet.cell_value(r, 6))) for r in range(4, 7)) == 60, "excel-mileage")
    call("get", f"/api/export/cover/{period}")
    printed = call("get", f"/api/periods/{period}/invoices/print").get_data(as_text=True)
    require(printed.count('alt="发票原件"') == 1, "print-selection")
    cache = Path(app.config["UPLOAD_DIR"]) / "reimbursement" / fuel["file_url"].rsplit("/", 1)[-1]
    cache.unlink(missing_ok=True)  # Only this run's file in its private TemporaryDirectory.
    require(call("get", fuel["file_url"].removeprefix(prefix)).data == original, "blob-original-recovery")
    other = app.test_client()
    require(other.get(prefix + f"/api/summary/{period}").status_code == 404, "owner-summary-isolation")
    require(other.get(fuel["file_url"]).status_code == 404, "owner-original-isolation")
    entries = call("get", f"/api/periods/{period}/audits").json["audits"]
    audit_id = next(row["id"] for row in entries if row["action"] == "toll.allocate")
    call("post", path + "/undo", json={"audit_id":audit_id})
    require(call("get", f"/api/summary/{period}").json["summary"]["total_amount"] == 60, "undo-total")
    print("BUSINESS_OK: retention, allocation, stale-write, Excel, print, original, isolation, undo")


def main():
    require(len(sys.argv) == 2, "candidate-directory-required")
    root = Path(sys.argv[1]).resolve(strict=True)
    require(not (root / ".env").exists(), "candidate-must-not-have-dotenv")
    require((root / "migrations/versions/e4f5a6b7c8d9_invoice_retention.py").is_file(), "candidate-revision-required")
    require(os.name == "posix" and os.geteuid() != 0, "run-as-postgres-not-root")
    os.chdir(root)
    sys.path.insert(0, str(root))
    from flask import Flask
    from sqlalchemy import text
    from extensions import db, csrf, limiter, login_manager
    from models import User
    from tools.reimbursement import tool_bp

    with tempfile.TemporaryDirectory(prefix="invoice-smoke-") as uploads:
        app = Flask(__name__, root_path=str(root))
        app.config.update(SECRET_KEY=secrets.token_urlsafe(32), TESTING=True,
            SQLALCHEMY_DATABASE_URI=f"postgresql+psycopg2://postgres@/{VERIFY_DATABASE}?host=/var/run/postgresql&port=5432",
            WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False, SESSION_PROTECTION=None,
            UPLOAD_DIR=uploads, DAILY_FREE_LIMIT=100, ANON_FREE_LIMIT=10)
        db.init_app(app)
        csrf.init_app(app)
        limiter.init_app(app)
        login_manager.init_app(app)
        login_manager.user_loader(lambda uid: db.session.get(User, int(uid)))
        app.register_blueprint(tool_bp, url_prefix="/tools/reimbursement")
        with app.app_context():
            require(db.session.execute(text("SELECT current_database()")).scalar() == VERIFY_DATABASE, "wrong-database")
            require(db.session.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [REVISION], "wrong-revision")
            before = historical_snapshot(db)
        try:
            exercise(app)
        finally:
            with app.app_context():
                db.session.rollback()
                require(historical_snapshot(db, before) == before, "historical-data-changed")
        print("HISTORY_OK: restored invoice and original attachment rows unchanged")
        print("STAGING_SMOKE_OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # No customer content, DSN, traceback, or internal database errors to chat.
        label = str(exc) if isinstance(exc, CheckFailure) else "unexpected-error"
        print(f"STAGING_SMOKE_FAILED: {label}; stop release", file=sys.stderr)
        sys.exit(1)
