from __future__ import annotations

import base64
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from flask import Flask, jsonify, send_file
from flask_wtf.csrf import generate_csrf

from extensions import csrf, db, limiter, login_manager
from models import ReimbursementAttachment
from tools.reimbursement import tool_bp as reimbursement_bp
from tools.zip_extractor import MB, _extract_deep, analyze_uploaded_archives, invoice_zip_limits
from utils.helpers import safe_download_path, safe_filename, stage_download


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n1cAAAAASUVORK5CYII="
)


def make_reimbursement_app(upload_dir: str) -> Flask:
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SECRET_KEY="phase-a-security-test",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_DIR=upload_dir,
        ANON_FREE_LIMIT=10,
        DAILY_FREE_LIMIT=10,
        RATELIMIT_ENABLED=False,
        WTF_CSRF_ENABLED=True,
    )
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.user_loader(lambda _user_id: None)
    csrf.init_app(app)
    limiter.init_app(app)

    @app.get("/_csrf")
    def csrf_token():
        return jsonify(token=generate_csrf())

    app.register_blueprint(reimbursement_bp, url_prefix="/tools/reimbursement")
    with app.app_context():
        db.create_all()
    return app


def csrf_headers(client) -> dict[str, str]:
    return {"X-CSRFToken": client.get("/_csrf").get_json()["token"]}


def make_download_app(upload_dir: str) -> Flask:
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="download-session-test", UPLOAD_DIR=Path(upload_dir))

    @app.get("/issue")
    def issue_download():
        filename = safe_filename("result.txt")
        target = Path(app.config["UPLOAD_DIR"]) / filename
        target.write_text("private result", encoding="utf-8")
        return jsonify(filename=filename)

    @app.get("/download/<filename>")
    def download(filename: str):
        target = safe_download_path(Path(app.config["UPLOAD_DIR"]), filename)
        if target is None or not target.exists():
            return jsonify(error="not found"), 404
        return send_file(target, as_attachment=True)

    return app


class PhaseASecurityTests(unittest.TestCase):
    def test_invoice_zip_limits_follow_flask_request_cap(self):
        app = Flask(__name__)
        app.config.update(
            MAX_CONTENT_LENGTH=10 * MB,
            INVOICE_ZIP_MAX_MB=20,
            INVOICE_ZIP_BATCH_MB=20,
            INVOICE_ZIP_RESPONSE_MB=48,
        )
        with app.app_context():
            limits = invoice_zip_limits()
        self.assertEqual(limits["single_mb"], 9)
        self.assertEqual(limits["batch_mb"], 9)
        self.assertEqual(limits["response_bytes"], 48 * MB)

    def test_unified_invoice_endpoint_reuses_secure_extractor_and_usage_id(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="invoice-unified-test")

        @app.post("/analyze")
        def analyze_invoice_zip():
            return analyze_uploaded_archives("invoice_printer")

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("nested/invoice.pdf", b"%PDF-1.4\n%%EOF\n")

        with patch("tools.zip_extractor.commit_usage") as commit:
            response = app.test_client().post(
                "/analyze",
                data={"files": [(io.BytesIO(archive.getvalue()), "invoices.zip")]},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["files"][0]["filename"], "invoice.pdf")
        commit.assert_called_once_with("invoice_printer", success=True)

    def test_invoice_archive_returns_every_pdf_and_per_archive_counts(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="invoice-mixed-queue-test",
            MAX_CONTENT_LENGTH=25 * MB,
        )

        @app.post("/analyze")
        def analyze_invoice_zip():
            return analyze_uploaded_archives("invoice_printer")

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("receipts/first.pdf", b"%PDF-1.4\nfirst\n%%EOF\n")
            zf.writestr("receipts/second.pdf", b"%PDF-1.4\nsecond\n%%EOF\n")

        empty_archive = io.BytesIO()
        with zipfile.ZipFile(empty_archive, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("README.txt", b"no invoice in this archive")

        with patch("tools.zip_extractor.commit_usage") as commit:
            response = app.test_client().post(
                "/analyze",
                data={
                    "files": [
                        (io.BytesIO(archive.getvalue()), "mixed.zip"),
                        (io.BytesIO(empty_archive.getvalue()), "empty.zip"),
                    ]
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual(
            {item["filename"] for item in payload["files"]},
            {"first.pdf", "second.pdf"},
        )
        self.assertEqual(
            payload["archive_results"],
            [
                {"name": "mixed.zip", "pdf_count": 2, "nested_archives": 0},
                {"name": "empty.zip", "pdf_count": 0, "nested_archives": 0},
            ],
        )
        commit.assert_called_once_with("invoice_printer", success=True)

    def test_invoice_endpoint_recurses_through_extensionless_nested_archives(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="invoice-recursive-test",
            MAX_CONTENT_LENGTH=25 * MB,
        )

        @app.post("/analyze")
        def analyze_invoice_zip():
            return analyze_uploaded_archives("invoice_printer")

        leaf = io.BytesIO()
        with zipfile.ZipFile(leaf, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("发票目录\\电子发票", b"%PDF-1.4\nrecursive\n%%EOF\n")

        middle = io.BytesIO()
        with zipfile.ZipFile(middle, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("无扩展名内层包", leaf.getvalue())

        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("批次目录\\第二层.ZIP", middle.getvalue())

        with patch("tools.zip_extractor.commit_usage") as commit:
            response = app.test_client().post(
                "/analyze",
                data={"files": [(io.BytesIO(outer.getvalue()), "outer.zip")]},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["files"][0]["filename"], "电子发票.pdf")
        self.assertEqual(payload["archive_results"][0]["pdf_count"], 1)
        self.assertEqual(payload["archive_results"][0]["nested_archives"], 2)
        self.assertIn("无扩展名内层包", payload["files"][0]["path_chain"][0])
        commit.assert_called_once_with("invoice_printer", success=True)

    def test_invalid_invoice_zip_returns_per_archive_diagnostics(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="invoice-diagnostics-test")

        @app.post("/analyze")
        def analyze_invoice_zip():
            return analyze_uploaded_archives("invoice_printer")

        with patch("tools.zip_extractor.commit_usage") as commit:
            response = app.test_client().post(
                "/analyze",
                data={"files": [(io.BytesIO(b"not-a-zip"), "broken.zip")]},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertEqual(payload["archive_results"][0]["name"], "broken.zip")
        self.assertIn("不是有效 ZIP", payload["archive_results"][0]["issues"][0])
        commit.assert_not_called()

    def test_invoice_zip_larger_than_legacy_four_mb_limit_is_accepted(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="invoice-large-test",
            MAX_CONTENT_LENGTH=25 * MB,
            INVOICE_ZIP_MAX_MB=20,
            INVOICE_ZIP_BATCH_MB=20,
            INVOICE_ZIP_RESPONSE_MB=48,
        )

        @app.post("/analyze")
        def analyze_invoice_zip():
            return analyze_uploaded_archives("invoice_printer")

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("invoice.pdf", b"%PDF-1.4\n" + b"A" * (5 * MB) + b"\n%%EOF")

        with patch("tools.zip_extractor.commit_usage") as commit:
            response = app.test_client().post(
                "/analyze",
                data={"files": [(io.BytesIO(archive.getvalue()), "five-mb.zip")]},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total"], 1)
        commit.assert_called_once_with("invoice_printer", success=True)

    def test_oversize_invoice_zip_is_rejected_without_charging_usage(self):
        app = Flask(__name__)
        app.config.update(
            TESTING=True,
            SECRET_KEY="invoice-oversize-test",
            MAX_CONTENT_LENGTH=30 * MB,
            INVOICE_ZIP_MAX_MB=20,
            INVOICE_ZIP_BATCH_MB=25,
        )

        @app.post("/analyze")
        def analyze_invoice_zip():
            return analyze_uploaded_archives("invoice_printer")

        with patch("tools.zip_extractor.commit_usage") as commit:
            response = app.test_client().post(
                "/analyze",
                data={"files": [(io.BytesIO(b"x" * (21 * MB)), "too-large.zip")]},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 413)
        self.assertFalse(response.get_json()["success"])
        commit.assert_not_called()

    def test_reimbursement_rejects_write_without_csrf_token(self):
        with tempfile.TemporaryDirectory() as upload_dir:
            app = make_reimbursement_app(upload_dir)
            client = app.test_client()
            response = client.post(
                "/tools/reimbursement/upload",
                data={"file": (io.BytesIO(PNG_1X1), "invoice.png")},
                content_type="multipart/form-data",
            )
            self.assertEqual(response.status_code, 400)

    def test_attachment_preview_and_ocr_are_owner_scoped(self):
        with tempfile.TemporaryDirectory() as upload_dir:
            app = make_reimbursement_app(upload_dir)
            owner = app.test_client()
            attacker = app.test_client()
            uploaded = owner.post(
                "/tools/reimbursement/upload",
                headers=csrf_headers(owner),
                data={"file": (io.BytesIO(PNG_1X1), "invoice.png")},
                content_type="multipart/form-data",
            )
            self.assertEqual(uploaded.status_code, 200)
            payload = uploaded.get_json()

            # The old client-controlled anonymous header must not change the
            # owner resolved from the signed Flask session.
            forged = {**csrf_headers(attacker), "X-RB-Anon-Id": "owner-session-id"}
            preview = attacker.get(payload["original_url"], headers={"X-RB-Anon-Id": "owner-session-id"})
            self.assertEqual(preview.status_code, 404)
            ocr = attacker.post("/tools/reimbursement/ocr", headers=forged, json={"file_id": payload["file_id"]})
            self.assertEqual(ocr.status_code, 404)

            with app.app_context():
                self.assertEqual(ReimbursementAttachment.query.count(), 1)

    def test_ocr_rejects_noncanonical_file_ids_before_lookup(self):
        with tempfile.TemporaryDirectory() as upload_dir:
            app = make_reimbursement_app(upload_dir)
            client = app.test_client()
            response = client.post(
                "/tools/reimbursement/ocr",
                headers=csrf_headers(client),
                json={"file_id": "../../instance/app.db"},
            )
            self.assertEqual(response.status_code, 400)

    def test_zip_member_with_dangerous_compression_ratio_is_not_read(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bomb.pdf", b"A" * (512 * 1024))
        self.assertEqual(_extract_deep(archive.getvalue(), "bomb.zip"), [])

    def test_staged_download_is_bound_to_issuing_session(self):
        with tempfile.TemporaryDirectory() as upload_dir:
            app = make_download_app(upload_dir)
            owner = app.test_client()
            attacker = app.test_client()
            filename = owner.get("/issue").get_json()["filename"]
            owner_response = owner.get(f"/download/{filename}")
            self.assertEqual(owner_response.status_code, 200)
            owner_response.close()
            attacker_response = attacker.get(f"/download/{filename}")
            self.assertEqual(attacker_response.status_code, 404)
            attacker_response.close()

    def test_stage_download_rejects_path_components(self):
        with tempfile.TemporaryDirectory() as upload_dir:
            app = Flask(__name__)
            app.config.update(SECRET_KEY="stage-download-test", UPLOAD_DIR=upload_dir)
            with app.test_request_context("/"):
                filename = safe_filename("result.txt")
                self.assertEqual(stage_download(filename, b"private result"), filename)
                self.assertEqual((Path(upload_dir) / filename).read_bytes(), b"private result")
                with self.assertRaises(ValueError):
                    stage_download("../outside.txt", b"must not write")
                with self.assertRaises(ValueError):
                    stage_download("..", b"must not write")


if __name__ == "__main__":
    unittest.main()
