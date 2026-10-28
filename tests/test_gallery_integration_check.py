from __future__ import annotations

import unittest

from flask import Flask

from utils.integration_check import gallery_integration_checks


class GalleryIntegrationCheckTests(unittest.TestCase):
    def test_complete_shared_domain_configuration_passes(self):
        app = Flask(__name__)
        app.config.update(
            APP_BASE_URL="https://tools.example.com",
            AI_IMAGE_EXTERNAL_URL="https://ai.example.com/create",
            GALLERY_INTROSPECTION_SECRET="x" * 32,
            SESSION_COOKIE_DOMAIN=".example.com",
            SESSION_COOKIE_SECURE=True,
            GALLERY_SERVICE_BASE_URL="https://api.example.com",
            GALLERY_INTERNAL_HMAC_SECRET="y" * 32,
        )
        self.assertTrue(all(check.ok for check in gallery_integration_checks(app)))

    def test_missing_configuration_fails_without_exposing_values(self):
        app = Flask(__name__)
        app.config.update(APP_BASE_URL="https://tools.example.com")
        checks = gallery_integration_checks(app)
        self.assertFalse(all(check.ok for check in checks))
        rendered = " ".join(check.message for check in checks)
        self.assertNotIn("x" * 32, rendered)
        self.assertIn("gallery_service_url", {check.name for check in checks})
        self.assertIn("gallery_hmac_secret", {check.name for check in checks})

    def test_unrelated_cookie_domain_is_rejected(self):
        app = Flask(__name__)
        app.config.update(
            APP_BASE_URL="https://tools.example.com",
            AI_IMAGE_EXTERNAL_URL="https://gallery.other.example/create",
            GALLERY_INTROSPECTION_SECRET="x" * 32,
            SESSION_COOKIE_DOMAIN=".example.com",
            SESSION_COOKIE_SECURE=True,
            GALLERY_SERVICE_BASE_URL="https://api.example.com",
            GALLERY_INTERNAL_HMAC_SECRET="y" * 32,
        )
        result = {check.name: check.ok for check in gallery_integration_checks(app)}
        self.assertFalse(result["shared_cookie_domain"])


if __name__ == "__main__":
    unittest.main()
