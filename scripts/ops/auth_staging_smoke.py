"""Application smoke on the migrated, dedicated restore database only.

Synthetic WeChat exchange and in-memory mail capture; no listener or .env.
"""
import os
from pathlib import Path
import secrets
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ops.mobile_invoice_staging_smoke import exercise, snapshot, require, CheckFailure

DATABASE = 'auth_rehearsal_20261116'


def exercise_unified(app):
    from extensions import db
    from models import User, UserToolGrant
    from auth import email_service
    from auth.account_models import AuthMailJob
    exercise(app, unified=True)
    mobile = app.test_client(use_cookies=False)
    subject = 'auth-stage-' + secrets.token_hex(16)
    with patch('auth.mobile_service.exchange_code', return_value=subject):
        signed = mobile.post('/api/mobile/session', json={'code':'synthetic'})
        require(signed.status_code == 200, 'signup-failed')
        old_headers = {'Authorization':'Bearer '+signed.json['access_token']}
        account = mobile.get('/api/mobile/account', headers=old_headers).json
        uid = account['account_id']
        with app.app_context():
            user = db.session.get(User, uid)
            require(not user.is_admin and user.email is None and user.password_hash is None, 'signup-privilege')
            require([g.tool_id for g in UserToolGrant.query.filter_by(user_id=uid)] == ['reimbursement'], 'signup-grants')
        require(mobile.get('/api/mobile/bootstrap', headers=old_headers).status_code == 200, 'signup-not-immediately-usable')
        email = 'auth-stage-'+secrets.token_hex(12)+'@example.com'
        password = secrets.token_urlsafe(24)+'a1'
        saved = mobile.post('/api/mobile/account/password', headers=old_headers,
            json={'code':'synthetic-fresh','email':email,'password':password})
        require(saved.status_code == 200, 'website-password-setup-failed')
    require(mobile.get('/api/mobile/account', headers=old_headers).status_code == 401, 'old-token-survived-setup')
    headers = {'Authorization':'Bearer '+saved.json['access_token']}
    require(mobile.get('/api/mobile/account', headers=headers).json['account_id'] == uid, 'account-id-changed')
    web = app.test_client()
    require(web.post('/login', data={'email':email,'password':password}).status_code == 302, 'website-login-failed')
    with app.app_context():
        ids = [j.id for j in AuthMailJob.query.filter_by(user_id=uid)]
        require(email_service.dispatch(job_ids=ids)['sent'] >= 1, 'capture-mail-failed')
        raw = app.extensions['auth_mail_capture'][-1][2].split('#')[1].split('\n')[0]
        require(email_service.consume(raw, 'verify'), 'verify-failed')
        require(not email_service.consume(raw, 'verify'), 'verify-replay')
        require(email_service.enqueue(uid, 'reset', email), 'reset-queue-failed')
        db.session.commit()
        email_service.dispatch(job_ids=[j.id for j in AuthMailJob.query.filter_by(user_id=uid)])
        raw = app.extensions['auth_mail_capture'][-1][2].split('#')[1].split('\n')[0]
        require(email_service.consume(raw, 'reset', password+'2'), 'reset-failed')
    require(mobile.get('/api/mobile/account', headers=headers).status_code == 401, 'reset-mobile-not-revoked')
    require(web.get('/account/security').status_code in (302, 401), 'reset-web-not-revoked')
    print('AUTH_APPLICATION_OK: signup, invoice-grant, same-account, website-login, captured-email, reset, revoke')


def main(*, registration=False):
    require(os.name == 'posix' and os.geteuid() != 0, 'run-as-postgres')
    require(not (ROOT/'.env').exists(), 'candidate-must-not-have-dotenv')
    os.chdir(ROOT)
    from flask import Flask
    from sqlalchemy import text
    from extensions import db, csrf, limiter, login_manager
    from auth.routes import auth_bp
    from auth.email_routes import security_bp
    from auth.mobile_routes import binding_bp, mobile_bp
    from auth.session_service import load_web_user
    from tools.reimbursement import tool_bp
    with tempfile.TemporaryDirectory(prefix='auth-staging-') as uploads:
        app = Flask(__name__, root_path=str(ROOT))
        app.config.update(TESTING=True, SECRET_KEY=secrets.token_urlsafe(32), SESSION_PROTECTION=None,
            SQLALCHEMY_DATABASE_URI=f'postgresql+psycopg2://postgres@/{DATABASE}?host=/var/run/postgresql&port=5432',
            WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False, UPLOAD_DIR=uploads,
            DAILY_FREE_LIMIT=100, ANON_FREE_LIMIT=10, WECHAT_MINI_ENABLED=True,
            WECHAT_MINI_APP_ID='wxe79848a64a839db8', WECHAT_MINI_APP_SECRET='synthetic-staging-only',
            WECHAT_MINI_REGISTRATION_ENABLED=True, AUTH_MAIL_ADAPTER='capture', APP_BASE_URL='https://mindfulpenpal.com')
        db.init_app(app); csrf.init_app(app); limiter.init_app(app); login_manager.init_app(app)
        login_manager.user_loader(load_web_user)
        for bp in (auth_bp, security_bp, binding_bp, mobile_bp): app.register_blueprint(bp)
        app.register_blueprint(tool_bp, url_prefix='/tools/reimbursement')
        app.add_url_rule('/', 'home', lambda:'staging')
        with app.app_context():
            require(db.session.execute(text('SELECT current_database()')).scalar() == DATABASE, 'wrong-database')
            revision = 'd9e0f1a2b3c4' if registration else 'c8d9e0f1a2b3'
            require(db.session.execute(text('SELECT version_num FROM public.alembic_version')).scalars().all() == [revision], 'wrong-revision')
            before = snapshot(db)
            if registration:
                from scripts.ops.verified_registration_smoke import history
                all_before = history(db.session.connection())
        try:
            exercise_unified(app)
            if registration:
                from scripts.ops.verified_registration_smoke import exercise
                from jinja2 import ChoiceLoader, DictLoader
                # Render the real auth forms without bootstrapping the production
                # application shell, its navigation endpoints or scheduled jobs.
                app.jinja_loader = ChoiceLoader([DictLoader({'base.html':
                    '<!doctype html><html lang="zh-CN"><body>{% block content %}{% endblock %}</body></html>'}), app.jinja_loader])
                app.jinja_env.cache.clear()
                exercise(app)
        finally:
            with app.app_context():
                db.session.rollback()
                require(snapshot(db, before) == before, 'historical-data-changed')
                if registration:
                    all_after = history(db.session.connection())
                    require(all(not (rows-all_after[table]) for table,rows in all_before.items()), 'historical-record-changed')
        print('AUTH_HISTORY_OK: existing users, invoices and original BLOBs unchanged')
        print('AUTH_STAGING_OK')
        if registration:
            print('VERIFIED_REGISTRATION_STAGING_OK')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        label = str(exc) if isinstance(exc, CheckFailure) else 'unexpected-error'
        print('AUTH_STAGING_FAILED: '+label+'; stop release', file=sys.stderr)
        sys.exit(1)
