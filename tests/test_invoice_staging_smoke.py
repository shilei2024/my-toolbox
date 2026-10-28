"""The operator smoke exercises real HTTP routes and exported workbook cells."""
import tempfile
import unittest
from flask import Flask
from extensions import db, csrf, limiter, login_manager
from models import User
from tools.reimbursement import tool_bp
from scripts.ops.invoice_staging_smoke import exercise


class StagingSmokeTests(unittest.TestCase):
    def test_business_exercise(self):
        with tempfile.TemporaryDirectory() as uploads:
            app = Flask(__name__)
            app.config.update(TESTING=True, SECRET_KEY="test", SESSION_PROTECTION=None,
                SQLALCHEMY_DATABASE_URI="sqlite:///:memory:", WTF_CSRF_ENABLED=False,
                RATELIMIT_ENABLED=False, UPLOAD_DIR=uploads, DAILY_FREE_LIMIT=100, ANON_FREE_LIMIT=10)
            db.init_app(app)
            csrf.init_app(app)
            limiter.init_app(app)
            login_manager.init_app(app)
            login_manager.user_loader(lambda uid: db.session.get(User, int(uid)))
            app.register_blueprint(tool_bp, url_prefix="/tools/reimbursement")
            with app.app_context():
                db.create_all()
            exercise(app)
