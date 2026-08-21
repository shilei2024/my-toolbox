"""主站 /create 与 /gallery 必须跳转到独立部署的 Gallery，而不是 404。"""
from __future__ import annotations

import os
import unittest

from app import create_app  # noqa: E402


class GalleryExternalRedirectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["AI_IMAGE_EXTERNAL_URL"] = "https://gallery.example.com/create"
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = cls._previous_database_url

    def test_create_redirects_to_gallery_create(self) -> None:
        response = self.client.get("/create")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://gallery.example.com/create")

    def test_gallery_redirects_to_gallery_browse(self) -> None:
        response = self.client.get("/gallery")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://gallery.example.com/gallery")

    def test_homepage_exposes_responsive_main_and_gallery_navigation(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="navbar navbar-expand-lg site-navbar', response.data)
        self.assertIn(b'id="tool-library"', response.data)
        self.assertIn(b'class="tool-grid"', response.data)
        self.assertIn(b'href="/gallery"', response.data)

    def test_fails_closed_when_gallery_url_unconfigured(self) -> None:
        previous = self.app.config.get("AI_IMAGE_EXTERNAL_URL")
        self.app.config["AI_IMAGE_EXTERNAL_URL"] = ""
        try:
            self.assertEqual(self.client.get("/create").status_code, 404)
            self.assertEqual(self.client.get("/gallery").status_code, 404)
            self.assertNotIn(b'href="/gallery"', self.client.get("/").data)
        finally:
            self.app.config["AI_IMAGE_EXTERNAL_URL"] = previous


if __name__ == "__main__":
    unittest.main()
