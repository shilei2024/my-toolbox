from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from flask import Flask

# Make the repository root importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.gallery_cors import apply_gallery_cors, gallery_cors_origins


class GalleryCorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.config["AI_IMAGE_EXTERNAL_URL"] = "https://gallery.example.com"
        apply_gallery_cors(self.app)

        @self.app.get("/login")
        def login():  # pragma: no cover - route stub for CORS assertions
            return "login page"

        self.client = self.app.test_client()

    def test_trusted_origin_gets_credentials_cors_headers(self) -> None:
        response = self.client.get("/login", headers={"Origin": "https://gallery.example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "https://gallery.example.com")
        self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")

    def test_preflight_from_trusted_origin_is_allowed(self) -> None:
        response = self.client.options(
            "/login",
            headers={
                "Origin": "https://gallery.example.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "RSC, Next-Router-State-Tree",
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), "https://gallery.example.com")
        self.assertEqual(response.headers.get("Access-Control-Allow-Credentials"), "true")
        self.assertIn("GET", response.headers.get("Access-Control-Allow-Methods", ""))
        self.assertEqual(response.headers.get("Access-Control-Allow-Headers"), "RSC, Next-Router-State-Tree")

    def test_unknown_origin_gets_no_cors_headers(self) -> None:
        response = self.client.get("/login", headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_preflight_from_unknown_origin_is_not_short_circuited(self) -> None:
        response = self.client.options(
            "/login",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotEqual(response.status_code, 204)
        self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))

    def test_extra_origin_via_environment(self) -> None:
        os.environ["GALLERY_CORS_ORIGINS"] = "https://preview-gallery.example.com"
        try:
            origins = gallery_cors_origins(self.app)
            self.assertIn("https://gallery.example.com", origins)
            self.assertIn("https://preview-gallery.example.com", origins)
        finally:
            os.environ.pop("GALLERY_CORS_ORIGINS", None)

    def test_unconfigured_origin_set_is_empty(self) -> None:
        self.app.config["AI_IMAGE_EXTERNAL_URL"] = ""
        os.environ.pop("GALLERY_CORS_ORIGINS", None)
        self.assertEqual(gallery_cors_origins(self.app), set())


if __name__ == "__main__":
    unittest.main()
