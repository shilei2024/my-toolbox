import tempfile
import unittest
from flask import Flask
from extensions import db,csrf,limiter,login_manager
from models import User, Tool
from auth.mobile_routes import binding_bp,mobile_bp
from tools.reimbursement import tool_bp
from tools.reimbursement.mobile_models import UploadReceipt  # noqa: F401, schema metadata
from scripts.ops.mobile_invoice_staging_smoke import exercise


class MobileStagingSmokeTests(unittest.TestCase):
    def test_real_business_routes(self):
        with tempfile.TemporaryDirectory() as uploads:
            app=Flask(__name__)
            app.config.update(TESTING=True,SECRET_KEY='test',SESSION_PROTECTION=None,
                SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',WTF_CSRF_ENABLED=False,RATELIMIT_ENABLED=False,
                UPLOAD_DIR=uploads,DAILY_FREE_LIMIT=100,ANON_FREE_LIMIT=10,WECHAT_MINI_ENABLED=True,
                WECHAT_MINI_APP_ID='wxe79848a64a839db8',WECHAT_MINI_APP_SECRET='synthetic-staging-only-not-a-secret')
            db.init_app(app);csrf.init_app(app);limiter.init_app(app);login_manager.init_app(app)
            login_manager.user_loader(lambda uid:db.session.get(User,int(uid)))
            app.register_blueprint(binding_bp);app.register_blueprint(mobile_bp)
            app.register_blueprint(tool_bp,url_prefix='/tools/reimbursement')
            with app.app_context():
                db.create_all()
                db.session.add(Tool(id='reimbursement',name='报销助手',route='/tools/reimbursement',blueprint_module='tools.reimbursement',required_plan='private'))
                db.session.commit()
            exercise(app)
