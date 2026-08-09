from __future__ import annotations

import unittest

from flask import Flask

from utils.pdf_limits import PdfResourceLimitError, enforce_pdf_file_count, enforce_pdf_page_count


class PdfResourceLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.config.update(MAX_PDF_FILES=2, MAX_PDF_PAGES=3)

    def test_rejects_excessive_file_and_page_counts(self) -> None:
        with self.app.app_context():
            enforce_pdf_file_count([object(), object()])
            enforce_pdf_page_count(3)
            with self.assertRaises(PdfResourceLimitError):
                enforce_pdf_file_count([object(), object(), object()])
            with self.assertRaises(PdfResourceLimitError):
                enforce_pdf_page_count(4)
