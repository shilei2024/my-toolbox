"""New registration closure on dedicated restored d9 database; no real mail."""
from collections import Counter
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ops.mobile_invoice_staging_smoke import CheckFailure, require


def history(conn, schema='public'):
    import sqlalchemy as sa
    require(schema == 'public' or re.fullmatch(r'auth_rehearsal_[a-z0-9_]+', schema), 'invalid-schema')
    tables = sa.inspect(conn).get_table_names(schema=schema)
    prefix = conn.dialect.identifier_preparer.quote_identifier(schema)+'.'
    return {table:Counter(conn.exec_driver_sql('SELECT md5(to_jsonb(t)::text) FROM '+prefix+
        conn.dialect.identifier_preparer.quote_identifier(table)+' t').scalars()) for table in tables}


def exercise(app):
    from extensions import db
    from models import User, UserToolGrant
    from auth import email_service
    from auth.account_models import AccountRegistration, AuthMailJob, WebSession
    origin = 'https://mindfulpenpal.com'
    app.config.update(WTF_CSRF_ENABLED=True, WTF_CSRF_SSL_STRICT=True)
    client = app.test_client()
    email = 'registration-stage-'+secrets.token_hex(10)+'@example.com'
    password = secrets.token_urlsafe(24)+'a1'

    def token(path):
        response = client.get(path, base_url=origin)
        require(response.status_code == 200, 'form-get-failed')
        found = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.get_data(as_text=True))
        require(found is not None, 'csrf-missing')
        return found.group(1)

    def post(path, values):
        return client.post(path, base_url=origin, data={'csrf_token':token(path), **values},
            headers={'Referer':origin+path})

    def deliver(**filters):
        with app.app_context():
            ids = [j.id for j in AuthMailJob.query.filter_by(**filters)]
            require(email_service.dispatch(job_ids=ids)['sent'] == 1, 'capture-delivery-failed')
            return app.extensions['auth_mail_capture'][-1]

    with app.app_context(): before_users = User.query.count()
    require(post('/register', {'email':email}).status_code == 302, 'registration-request-failed')
    with app.app_context():
        require(User.query.count() == before_users, 'unverified-account-created')
        row = AccountRegistration.query.filter_by(email=email).one()
        registration_id = row.id
    mail = deliver(registration_id=registration_id)
    raw = mail[2].split('#')[1].split('\n')[0]
    require(post('/account/email/register', {'token':raw,'password':password,'confirm':password}).status_code == 302, 'registration-confirmation-failed')
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        uid = user.id
        require(bool(user.email_verified_at) and not user.is_admin, 'registered-user-state')
        require(UserToolGrant.query.filter_by(user_id=uid).count() == 0, 'unexpected-private-grant')
        require(WebSession.query.filter_by(user_id=uid).count() == 0, 'unexpected-session')
    require('注册成功' in deliver(user_id=uid)[1], 'welcome-mail-missing')
    require(post('/login', {'email':email,'password':password}).status_code == 302, 'login-failed')
    require(post('/account/recover', {'email':email}).status_code == 200, 'recovery-request-failed')
    mail = deliver(user_id=uid)
    raw = mail[2].split('#')[1].split('\n')[0]
    replacement = password+'2'
    require(post('/account/email/reset', {'token':raw,'password':replacement,'confirm':replacement}).status_code == 302, 'password-reset-failed')
    require(client.get('/account/security',base_url=origin).status_code in (302,401), 'old-session-not-revoked')
    require(post('/login', {'email':email,'password':replacement}).status_code == 302, 'new-password-login-failed')
    print('VERIFIED_REGISTRATION_OK: pending, HTTPS-CSRF, verify, welcome, login, reset, revoke, new-password')


if __name__ == '__main__':
    from scripts.ops.auth_staging_smoke import main
    try:
        main(registration=True)
    except Exception as exc:
        label = str(exc) if isinstance(exc, CheckFailure) else 'unexpected-error'
        print('VERIFIED_REGISTRATION_STAGING_FAILED: '+label+'; stop release', file=sys.stderr)
        sys.exit(1)
