import unittest
from tests import test_mobile_invoice_upload as fixtures
from scripts.ops.auth_staging_smoke import exercise_unified


class AuthStagingTests(unittest.TestCase):
    setUp = fixtures.MobileInvoiceTests.setUp
    def test_unified_restore_harness(self):
        from auth.routes import auth_bp
        from auth.email_routes import security_bp
        from auth.session_service import load_web_user
        from extensions import login_manager
        self.app.config.update(WECHAT_MINI_REGISTRATION_ENABLED=True,
            AUTH_MAIL_ADAPTER='capture', APP_BASE_URL='https://mindfulpenpal.com')
        self.app._got_first_request = False
        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(security_bp)
        self.app.add_url_rule('/', 'home', lambda:'staging')
        login_manager.user_loader(load_web_user)
        exercise_unified(self.app)
