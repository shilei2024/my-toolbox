"""HTTPS browser form contract, with CSRF and strict referrer checks enabled."""
import re
import unittest
from pathlib import Path
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from extensions import db
from models import User
from auth import email_service
from auth.email_routes import security_bp
from tests import test_auth_service_phase2 as fixtures

ORIGIN = 'https://mindfulpenpal.com'


class EmailHttpsTests(unittest.TestCase):
    def setUp(self):
        fixtures.AuthServiceTests.setUp(self)
        self.app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_SSL_STRICT=True,
            AUTH_MAIL_ADAPTER='capture', APP_BASE_URL=ORIGIN)
        self.app.register_blueprint(security_bp)
        self.app.jinja_loader = ChoiceLoader([
            DictLoader({'base.html':'{% block content %}{% endblock %}'}),
            FileSystemLoader(Path(__file__).resolve().parents[1]/'templates')])

    def form(self, path):
        page = self.client.get(path, base_url=ORIGIN)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers['Referrer-Policy'], 'same-origin')
        body = page.get_data(as_text=True)
        if path.startswith('/account/email/'):
            self.assertIn('name="referrer" content="same-origin"', body)
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body).group(1)

    def post(self, path, data):
        return self.client.post(path, base_url=ORIGIN, data=data,
            headers={'Referer':ORIGIN+path})

    def mail_token(self):
        with self.app.app_context():
            self.assertEqual(email_service.dispatch()['sent'], 1)
            return self.app.extensions['auth_mail_capture'][-1][2].split('#')[1].split('\n')[0]

    def test_verify_recover_and_reset_with_real_https_csrf(self):
        # Generate a legitimate login form token; fixture template is real here.
        page = self.client.get('/login', base_url=ORIGIN)
        token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.get_data(as_text=True)).group(1)
        signed = self.post('/login', {'csrf_token':token,'email':'person@example.com','password':'password123'})
        self.assertEqual(signed.status_code, 302)
        csrf = self.form('/account/security')
        queued = self.post('/account/security', {'csrf_token':csrf,'action':'verify'})
        self.assertEqual(queued.status_code, 302)
        raw = self.mail_token()
        csrf = self.form('/account/email/verify')
        self.assertEqual(self.post('/account/email/verify', {'csrf_token':csrf,'token':raw}).status_code, 302)
        csrf = self.form('/account/recover')
        self.assertEqual(self.post('/account/recover', {'csrf_token':csrf,'email':'person@example.com'}).status_code, 200)
        raw = self.mail_token()
        csrf = self.form('/account/email/reset')
        response = self.post('/account/email/reset', {'csrf_token':csrf,'token':raw,
            'password':'new-password123','confirm':'new-password123'})
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertTrue(db.session.get(User,1).check_password('new-password123'))
        self.assertEqual(self.client.get('/who', base_url=ORIGIN).json, {'id':None})

    def test_missing_token_and_cross_origin_are_still_rejected(self):
        csrf = self.form('/account/recover')
        self.assertEqual(self.post('/account/recover', {'email':'person@example.com'}).status_code, 400)
        response = self.client.post('/account/recover', base_url=ORIGIN,
            headers={'Referer':'https://other.example/'}, data={'csrf_token':csrf,'email':'person@example.com'})
        self.assertEqual(response.status_code, 400)
        # This reproduces the prior browser policy: valid token, absent Referer.
        self.assertEqual(self.client.post('/account/recover', base_url=ORIGIN,
            data={'csrf_token':csrf,'email':'person@example.com'}).status_code, 400)
