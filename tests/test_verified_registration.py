from datetime import timedelta
import unittest
from unittest.mock import patch
from extensions import db
from models import User, UserToolGrant, utcnow
from auth import email_service, registration_service
from auth.account_models import AccountRegistration, ActionToken, AuthMailJob, WebSession
from shared.mail import MailError
from tests import test_auth_email_https as https
ORIGIN = https.ORIGIN


class VerifiedRegistrationTests(unittest.TestCase):
    setUp = https.EmailHttpsTests.setUp
    form = https.EmailHttpsTests.form
    post = https.EmailHttpsTests.post
    def register(self, email='new@example.com', password='owner-password123', confirm=None):
        token = self.form('/account/registration/pending')
        return self.post('/register', {'csrf_token':token, 'email':email,
            'password':password, 'confirm':password if confirm is None else confirm})

    def registration_token(self):
        with self.app.app_context():
            self.assertEqual(email_service.dispatch()['sent'], 1)
            mail = self.app.extensions['auth_mail_capture'][-1]
            self.assertIn('完成注册', mail[1])
            return mail[2].split('#')[1].split('\n')[0]

    def activate(self, raw):
        csrf = self.form('/account/email/register-confirm')
        return self.post('/account/email/register-confirm', {'csrf_token':csrf, 'token':raw})

    def test_complete_https_registration_welcome_login_and_password_recovery(self):
        response = self.register()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/account/registration/pending')
        with self.app.app_context():
            self.assertEqual(User.query.count(), 1)
            self.assertEqual(WebSession.query.count(), 0)
        raw = self.registration_token()
        with self.app.app_context():
            self.assertNotEqual(AccountRegistration.query.one().token_hash, raw)
        # Opening the link alone must never activate the account.
        page = self.client.get('/account/email/register-confirm', base_url=ORIGIN)
        self.assertNotIn('name="password"', page.get_data(as_text=True))
        with self.app.app_context(): self.assertEqual(User.query.count(), 1)
        response = self.activate(raw)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/account/registration/complete')
        self.assertIn('注册成功', self.client.get(response.location, base_url=ORIGIN).get_data(as_text=True))
        with self.app.app_context():
            user = User.query.filter_by(email='new@example.com').one()
            self.assertIsNotNone(user.email_verified_at)
            self.assertFalse(user.is_admin)
            self.assertTrue(user.check_password('owner-password123'))
            self.assertIsNone(AccountRegistration.query.one().password_hash)
            self.assertEqual(UserToolGrant.query.count(), 0)
            self.assertEqual(WebSession.query.count(), 0)
            self.assertEqual(AuthMailJob.query.filter_by(purpose='welcome').count(), 1)
            self.assertEqual(email_service.dispatch()['sent'], 1)
            self.assertIn('注册成功', self.app.extensions['auth_mail_capture'][-1][1])
            self.assertEqual(ActionToken.query.count(), 0)
        self.assertEqual(self.activate(raw).status_code, 200)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 2)
            self.assertEqual(AuthMailJob.query.filter_by(purpose='welcome').count(), 1)
        self._assert_login_and_reset()

    def test_registration_password_validation_and_resend_immutability(self):
        page = self.client.get('/register',base_url=ORIGIN).get_data(as_text=True)
        for name in ('email','password','confirm'):
            self.assertIn('name="'+name+'"', page)
        self.assertEqual(self.register(password='weak').status_code, 200)
        self.assertEqual(self.register(confirm='different123').status_code, 200)
        with self.app.app_context(): self.assertEqual(AccountRegistration.query.count(), 0)
        self.register()
        old = self.registration_token()
        with self.app.app_context():
            row = AccountRegistration.query.one()
            self.assertNotEqual(row.password_hash, 'owner-password123')
            original_hash = row.password_hash
            row.last_requested_at = utcnow()-timedelta(minutes=2)
            db.session.commit()
            registration_service.request_registration('new@example.com',create=False)
            db.session.commit()
            self.assertEqual(AccountRegistration.query.one().password_hash, original_hash)
        new = self.registration_token()
        self.assertEqual(self.activate(old).status_code, 200)
        csrf = self.form('/account/email/register-confirm')
        self.assertEqual(self.post('/account/email/register-confirm', {'csrf_token':csrf,'token':new,
            'password':'unwanted123','confirm':'unwanted123'}).status_code, 302)
        with self.app.app_context():
            self.assertTrue(User.query.filter_by(email='new@example.com').one().check_password('owner-password123'))

    def test_resubmitted_password_invalidates_earlier_link(self):
        self.register()
        old = self.registration_token()
        with self.app.app_context():
            AccountRegistration.query.one().last_requested_at = utcnow()-timedelta(minutes=2)
            db.session.commit()
        self.register(password='replacement123')
        self.assertEqual(self.activate(old).status_code, 200)
        new = self.registration_token()
        self.assertEqual(self.activate(new).status_code, 302)
        with self.app.app_context():
            self.assertTrue(User.query.filter_by(email='new@example.com').one().check_password('replacement123'))

    def test_legacy_email_first_request_remains_usable(self):
        with self.app.app_context():
            db.session.add(AccountRegistration(email='legacy@example.com',
                last_requested_at=utcnow()-timedelta(minutes=2)))
            db.session.commit()
            registration_service.request_registration('legacy@example.com', create=False)
            db.session.commit()
        raw = self.registration_token()
        csrf = self.form('/account/email/register')
        self.assertEqual(self.post('/account/email/register', {'csrf_token':csrf,'token':raw,
            'password':'legacy-password123','confirm':'legacy-password123'}).status_code, 302)
        with self.app.app_context():
            self.assertTrue(User.query.filter_by(email='legacy@example.com').one().check_password('legacy-password123'))

    def _assert_login_and_reset(self):
        page = self.client.get('/login', base_url=ORIGIN)
        import re
        csrf = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.get_data(as_text=True)).group(1)
        self.assertEqual(self.post('/login', {'csrf_token':csrf, 'email':'new@example.com',
            'password':'owner-password123'}).status_code, 302)
        csrf = self.form('/account/recover')
        self.assertEqual(self.post('/account/recover', {'csrf_token':csrf, 'email':'new@example.com'}).status_code, 200)
        with self.app.app_context():
            self.assertEqual(email_service.dispatch()['sent'], 1)
            reset = self.app.extensions['auth_mail_capture'][-1][2].split('#')[1].split('\n')[0]
        csrf = self.form('/account/email/reset')
        self.assertEqual(self.post('/account/email/reset', {'csrf_token':csrf, 'token':reset,
            'password':'replacement123', 'confirm':'replacement123'}).status_code, 302)
        self.assertIsNone(self.client.get('/who', base_url=ORIGIN).json['id'])

    def test_mail_unavailable_creates_no_account_or_request(self):
        self.app.config['AUTH_MAIL_ADAPTER'] = 'disabled'
        self.assertEqual(self.register().status_code, 503)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 1)
            self.assertEqual(AccountRegistration.query.count(), 0)
            self.assertEqual(AuthMailJob.query.count(), 0)

    def test_operator_application_harness(self):
        from scripts.ops.verified_registration_smoke import exercise
        exercise(self.app)

    def test_resend_expiry_and_existing_account_are_safe(self):
        self.register()
        old = self.registration_token()
        self.register()
        with self.app.app_context():
            self.assertEqual(AuthMailJob.query.count(), 1)
            row = AccountRegistration.query.one()
            row.last_requested_at = utcnow()-timedelta(minutes=2)
            row.expires_at = utcnow()-timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(self.activate(old).status_code, 200)
        self.register()
        new = self.registration_token()
        self.assertNotEqual(old, new)
        self.assertEqual(self.activate(old).status_code, 200)
        self.assertEqual(self.activate(new).status_code, 302)
        response = self.register('person@example.com')
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(AccountRegistration.query.count(), 1)
            self.assertTrue(db.session.get(User,1).check_password('password123'))

    def test_pending_registration_never_replaces_existing_user(self):
        self.register()
        raw = self.registration_token()
        with self.app.app_context():
            # Another legitimate channel acquired this email before completion.
            user = User(email='new@example.com')
            user.set_password('existing-password123')
            db.session.add(user); db.session.commit()
        self.assertEqual(self.activate(raw).status_code, 200)
        with self.app.app_context():
            self.assertTrue(User.query.filter_by(email='new@example.com').one().check_password('existing-password123'))
            self.assertIsNone(AccountRegistration.query.one().completed_at)
            self.assertEqual(AuthMailJob.query.filter_by(purpose='welcome').count(), 0)

    def test_welcome_delivery_failure_does_not_undo_registration(self):
        self.register()
        raw = self.registration_token()
        self.assertEqual(self.activate(raw).status_code, 302)
        with self.app.app_context():
            self.app.config['AUTH_MAIL_ADAPTER'] = 'smtp'
            with patch('auth.email_service.ready', return_value=True), patch(
                'auth.email_service.send_smtp', side_effect=MailError('SMTP_DELIVERY_FAILED')):
                self.assertEqual(email_service.dispatch()['failed'], 1)
            job = AuthMailJob.query.filter_by(purpose='welcome').one()
            self.assertEqual(job.status, 'pending')
            job.next_attempt_at = utcnow()-timedelta(seconds=1)
            db.session.commit()
            self.assertIsNotNone(User.query.filter_by(email='new@example.com').one().email_verified_at)
            self.app.config['AUTH_MAIL_ADAPTER'] = 'capture'
            self.assertEqual(email_service.dispatch()['sent'], 1)
            self.assertEqual(ActionToken.query.count(), 0)
