import unittest
from unittest.mock import patch
from auth import email_service
from extensions import db
from shared.mail import send_smtp, MailError
from tests import test_auth_service_phase2 as fixtures


class AuthSenderTests(unittest.TestCase):
    setUp = fixtures.AuthServiceTests.setUp

    def smtp(self):
        self.app.config.update(AUTH_MAIL_ADAPTER='smtp', APP_BASE_URL='https://mindfulpenpal.com',
            SMTP_HOST='smtp.example.test', SMTP_PORT=587, SMTP_SECURITY='starttls',
            SMTP_TIMEOUT_SECONDS=10, SMTP_USERNAME='fixture', SMTP_PASSWORD='fixture-only',
            SMTP_FROM='项目跟进提醒 <projects@example.com>',
            AUTH_MAIL_FROM='账号安全 <accounts@example.com>',
            AUTH_MAIL_SMTP_USERNAME='accounts@example.com', AUTH_MAIL_SMTP_PASSWORD='auth-fixture-only')

    def test_auth_and_project_messages_keep_separate_identities(self):
        self.smtp()
        with self.app.app_context(), patch('shared.mail.smtplib.SMTP') as smtp:
            self.assertTrue(email_service.ready())
            self.assertTrue(email_service.enqueue(1, 'verify', 'person@example.com'))
            db.session.commit()
            self.assertEqual(email_service.dispatch()['sent'], 1)
            send_smtp('person@example.com', '项目提醒', 'fixture')
            messages = smtp.return_value.__enter__.return_value.send_message.call_args_list
            self.assertEqual(str(messages[0].args[0]['From']), '账号安全 <accounts@example.com>')
            self.assertEqual(str(messages[1].args[0]['From']), '项目跟进提醒 <projects@example.com>')
            self.assertEqual(self.app.config['SMTP_FROM'], '项目跟进提醒 <projects@example.com>')
            logins = smtp.return_value.__enter__.return_value.login.call_args_list
            self.assertEqual(logins[0].args, ('accounts@example.com', 'auth-fixture-only'))
            self.assertEqual(logins[1].args, ('fixture', 'fixture-only'))

    def test_empty_override_is_compatible_but_invalid_identity_is_rejected(self):
        self.smtp()
        with self.app.app_context():
            self.app.config['AUTH_MAIL_FROM'] = ''
            self.assertFalse(email_service.ready())
            self.app.config.update(AUTH_MAIL_SMTP_USERNAME='', AUTH_MAIL_SMTP_PASSWORD='')
            self.assertTrue(email_service.ready())
            self.app.config['AUTH_MAIL_FROM'] = 'invalid\r\nBcc: hidden@example.com'
            self.assertFalse(email_service.ready())
            with patch('shared.mail.smtplib.SMTP') as smtp:
                with self.assertRaises(MailError):
                    send_smtp('person@example.com','fixture','fixture',sender=self.app.config['AUTH_MAIL_FROM'])
                smtp.assert_not_called()

    def test_partial_credentials_never_fall_back_to_project_credentials(self):
        self.smtp()
        with self.app.app_context(), patch('shared.mail.smtplib.SMTP') as smtp:
            for username, password in (('accounts@example.com', ''), ('', 'auth-fixture-only')):
                self.app.config.update(AUTH_MAIL_SMTP_USERNAME=username, AUTH_MAIL_SMTP_PASSWORD=password)
                self.assertFalse(email_service.ready())
                self.assertFalse(email_service.enqueue(1, 'verify', 'person@example.com'))
                with self.assertRaises(MailError):
                    send_smtp('person@example.com', 'fixture', 'fixture', credentials=(username,password))
            smtp.assert_not_called()
