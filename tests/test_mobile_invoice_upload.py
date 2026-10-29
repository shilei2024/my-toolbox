import io
import json
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch
from flask import Flask
from sqlalchemy import event
from extensions import csrf, db, limiter, login_manager
from models import ReimbursementAttachment, ReimbursementInvoice, UsageLog, User, utcnow, Tool, UserToolGrant
from auth.mobile_models import BindingChallenge, ExternalIdentity, MobileSession
from auth.mobile_routes import binding_bp, mobile_bp
from tools.reimbursement import tool_bp
from tools.reimbursement.mobile_models import UploadReceipt

PNG = __import__('base64').b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n1cAAAAASUVORK5CYII=')


class MobileInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='test', SESSION_PROTECTION=None, SQLALCHEMY_DATABASE_URI=getattr(self, 'database_uri', 'sqlite:///:memory:'),
            WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False, UPLOAD_DIR=self.temp.name,
            WECHAT_MINI_ENABLED=True, WECHAT_MINI_APP_ID='wxe79848a64a839db8',
            WECHAT_MINI_APP_SECRET='unit-test-only-not-a-real-secret', DAILY_FREE_LIMIT=100, ANON_FREE_LIMIT=10)
        db.init_app(self.app); csrf.init_app(self.app); limiter.init_app(self.app); login_manager.init_app(self.app)
        login_manager.user_loader(lambda uid: db.session.get(User, int(uid)))
        self.app.register_blueprint(binding_bp)
        self.app.register_blueprint(mobile_bp)
        self.app.register_blueprint(tool_bp, url_prefix='/tools/reimbursement')
        with self.app.app_context():
            db.create_all()
            db.session.add(Tool(id='reimbursement',name='报销助手',route='/tools/reimbursement',blueprint_module='tools.reimbursement',required_plan='private'))
            db.session.flush()
            for index in range(2):
                user = User(email=f'mobile{index}@example.test')
                user.set_password('test-password')
                db.session.add(user)
                db.session.flush()
                db.session.add(UserToolGrant(user_id=user.id,tool_id='reimbursement'))
            db.session.commit()
        self.web = self.app.test_client()
        with self.web.session_transaction() as session:
            session['_user_id']='1'; session['_fresh']=True
        self.mobile = self.app.test_client(use_cookies=False)
        bootstrap = self.web.get('/tools/reimbursement/api/bootstrap').json
        self.office = bootstrap['offices'][0]['id']
        self.period = self.web.post('/tools/reimbursement/api/periods', json=dict(start_year=2026,start_month=6,end_year=2026,end_month=7)).json['period']['id']

    def challenge(self):
        response = self.web.post('/auth/mobile/challenge', json={'password':'test-password'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['qr_image'].startswith('data:image/png;base64,'))
        return response.json['binding_code']

    def test_revoked_tool_grant_blocks_mobile_data_but_allows_logout(self):
        headers=self.login()
        invoice=self.upload(headers).json['invoice']
        with self.app.app_context():
            db.session.delete(db.session.get(UserToolGrant,{'user_id':1,'tool_id':'reimbursement'}));db.session.commit()
        self.assertEqual(self.mobile.get('/api/mobile/bootstrap',headers=headers).status_code,403)
        self.assertEqual(self.mobile.get(invoice['file_endpoint'],headers=headers).status_code,403)
        self.assertEqual(self.upload(headers,key='revoked-upload-key-0001').status_code,403)
        self.assertEqual(self.web.post('/auth/mobile/challenge',json={'password':'test-password'}).status_code,403)
        self.assertEqual(self.mobile.post('/api/mobile/logout',headers=headers).status_code,200)

    def login(self, binding=True, subject='subject-a'):
        data={'code':'temporary-code'}
        if binding: data['binding_code']=self.challenge()
        with patch('auth.mobile_service.exchange_code', return_value=subject):
            response=self.mobile.post('/api/mobile/session', json=data)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertNotIn('Set-Cookie', response.headers)
        return {'Authorization':'Bearer '+response.json['access_token'], 'Accept':'application/json'}

    def upload(self, headers, key='upload-key-0000000001', kind='fuel', period=None, content=PNG, occurrence='2026-06'):
        return self.mobile.post('/api/mobile/invoices', headers=headers, data={
            'file':(io.BytesIO(content),'票据.png'), 'period_id':str(period or self.period), 'office_id':str(self.office),
            'document_kind':kind, 'occurrence_month':occurrence, 'idempotency_key':key})

    def test_cross_period_retention_preserves_occurrence_without_changing_expenses(self):
        response=self.upload(self.login(), occurrence='2026-08')
        self.assertEqual(response.status_code,201)
        self.assertEqual(response.json['invoice']['occurrence_month'],'2026-08')
        self.assertEqual(response.json['invoice']['period_id'],self.period)
        self.assertEqual(self.web.get(f'/tools/reimbursement/api/summary/{self.period}').json['summary']['total_amount'],0)

    def test_bound_login_upload_and_desktop_share_same_invoice_without_fee(self):
        headers=self.login()
        uploaded=self.upload(headers)
        self.assertEqual(uploaded.status_code,201,uploaded.json)
        invoice=uploaded.json['invoice']
        self.assertEqual(invoice['inclusion_policy'],'retain')
        summary=self.web.get(f'/tools/reimbursement/api/summary/{self.period}').json
        self.assertEqual(summary['summary']['total_amount'],0)
        listing=self.mobile.get(f'/api/mobile/invoices?period_id={self.period}',headers=headers).json
        self.assertEqual(listing['invoices'][0]['id'],invoice['id'])
        original=self.mobile.get(invoice['file_endpoint'],headers=headers)
        self.assertEqual(original.data,PNG)
        self.assertIn('no-store',original.headers['Cache-Control'])
        self.assertEqual(self.mobile.get('/api/mobile/bootstrap',headers=self.login(binding=False)).status_code,200)

    def test_cookie_cannot_authorize_mobile_and_token_cannot_authorize_website(self):
        headers=self.login()
        self.assertEqual(self.web.get('/api/mobile/bootstrap').status_code,401)
        self.assertEqual(self.web.get('/api/mobile/bootstrap',headers=headers).status_code,401)
        self.assertEqual(self.mobile.get(f'/tools/reimbursement/api/summary/{self.period}',headers=headers).status_code,404)
        self.assertEqual(self.mobile.get('/api/mobile/bootstrap').status_code,401)

    def test_token_and_binding_secrets_are_hashed_and_one_time(self):
        code=self.challenge()
        with patch('auth.mobile_service.exchange_code',return_value='subject-a'):
            response=self.mobile.post('/api/mobile/session',json={'code':'once','binding_code':code})
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.mobile.post('/api/mobile/session',json={'code':'again','binding_code':code}).status_code,400)
        with self.app.app_context():
            self.assertNotEqual(BindingChallenge.query.first().token_hash,code)
            self.assertNotEqual(MobileSession.query.first().token_hash,response.json['access_token'])

    def test_new_or_expired_binding_code_is_rejected(self):
        old=self.challenge(); self.challenge()
        with patch('auth.mobile_service.exchange_code',return_value='subject-a'):
            self.assertEqual(self.mobile.post('/api/mobile/session',json={'code':'a','binding_code':old}).status_code,400)
        code=self.challenge()
        with self.app.app_context():
            row=BindingChallenge.query.order_by(BindingChallenge.id.desc()).first();row.expires_at=utcnow()-timedelta(seconds=1);db.session.commit()
        with patch('auth.mobile_service.exchange_code',return_value='subject-a'):
            self.assertEqual(self.mobile.post('/api/mobile/session',json={'code':'a','binding_code':code}).status_code,400)

    def test_binding_expiring_while_waiting_for_user_lock_is_rejected(self):
        code=self.challenge()
        before=utcnow()
        clock=[before]
        with self.app.app_context():
            BindingChallenge.query.first().expires_at=before+timedelta(seconds=1)
            db.session.commit()
            engine=db.engine
        def delayed_user_lock(_conn,_cursor,statement,_parameters,_context,_executemany):
            if 'FROM users' in statement:
                clock[0]=before+timedelta(seconds=2)
        event.listen(engine,'before_cursor_execute',delayed_user_lock)
        try:
            with patch('auth.mobile_service.utcnow',side_effect=lambda:clock[0]), patch('auth.mobile_service.exchange_code',return_value='subject-a'):
                response=self.mobile.post('/api/mobile/session',json={'code':'test','binding_code':code})
            self.assertEqual(response.status_code,400)
            with self.app.app_context():
                self.assertEqual(MobileSession.query.count(),0)
                self.assertIsNone(BindingChallenge.query.first().consumed_at)
        finally:
            event.remove(engine,'before_cursor_execute',delayed_user_lock)

    def test_unbind_revokes_all_devices_and_cannot_silently_transfer(self):
        first=self.login(); second=self.login(binding=False)
        with self.web.session_transaction() as session: session['_user_id']='2'
        code=self.challenge()
        with patch('auth.mobile_service.exchange_code',return_value='subject-a'):
            self.assertEqual(self.mobile.post('/api/mobile/session',json={'code':'a','binding_code':code}).status_code,409)
        with self.web.session_transaction() as session: session['_user_id']='1'
        identity=self.web.get('/auth/mobile/bindings').json['bindings'][0]['id']
        self.assertEqual(self.web.delete(f'/auth/mobile/bindings/{identity}',json={'password':'test-password'}).status_code,200)
        for headers in (first,second): self.assertEqual(self.mobile.get('/api/mobile/bootstrap',headers=headers).status_code,401)

    def test_stopped_user_and_expired_token_are_rejected(self):
        headers=self.login()
        with self.app.app_context():
            user=db.session.get(User,1);user.is_active_user=False;db.session.commit()
        self.assertEqual(self.mobile.get('/api/mobile/bootstrap',headers=headers).status_code,401)
        with self.app.app_context():
            db.session.get(User,1).is_active_user=True
            MobileSession.query.first().expires_at=utcnow()-timedelta(seconds=1);db.session.commit()
        self.assertEqual(self.mobile.get('/api/mobile/bootstrap',headers=headers).status_code,401)

    def test_retry_returns_same_record_and_quota_once_and_changed_intent_conflicts(self):
        headers=self.login()
        first=self.upload(headers);second=self.upload(headers)
        self.assertEqual((first.status_code,second.status_code),(201,200))
        self.assertEqual(first.json['invoice']['id'],second.json['invoice']['id'])
        self.assertEqual(self.upload(headers,kind='toll').status_code,409)
        with self.app.app_context():
            self.assertEqual(ReimbursementInvoice.query.count(),1)
            self.assertEqual(ReimbursementAttachment.query.count(),1)
            self.assertEqual(UploadReceipt.query.count(),1)
            self.assertEqual(UsageLog.query.filter_by(tool_id='reimbursement',status='success').count(),1)
        duplicate=self.upload(headers,key='upload-key-0000000002')
        self.assertEqual(duplicate.status_code,200)
        self.assertEqual(self.upload(headers,key='upload-key-0000000003',kind='toll').status_code,409)
        with self.app.app_context(): self.assertEqual(ReimbursementInvoice.query.count(),1)

    def test_invalid_period_or_file_never_persists_or_charges(self):
        headers=self.login()
        self.assertEqual(self.upload(headers,period=9999).status_code,400)
        self.assertEqual(self.upload(headers,content=b'not an image').status_code,400)
        with self.app.app_context():
            self.assertEqual(ReimbursementAttachment.query.count(),0)
            self.assertEqual(ReimbursementInvoice.query.count(),0)
            self.assertEqual(UploadReceipt.query.count(),0)
            self.assertEqual(UsageLog.query.count(),0)

    def test_other_user_cannot_read_period_or_original(self):
        headers=self.login(); invoice=self.upload(headers).json['invoice']
        with self.web.session_transaction() as session: session['_user_id']='2'
        other=self.login(subject='subject-b')
        self.assertEqual(self.mobile.get(invoice['file_endpoint'],headers=other).status_code,404)
        self.assertEqual(self.mobile.get(f'/api/mobile/invoices?period_id={self.period}',headers=other).status_code,404)

    def test_plain_upload_pending_and_logout_revokes(self):
        headers=self.login(); invoice=self.upload(headers,kind='invoice').json['invoice']
        self.assertEqual(invoice['inclusion_policy'],'review')
        self.assertFalse(invoice['amount_confirmed'])
        self.assertEqual(self.mobile.post('/api/mobile/logout',headers=headers).status_code,200)
        self.assertEqual(self.mobile.get('/api/mobile/bootstrap',headers=headers).status_code,401)

    def test_feature_disabled_password_and_csrf_boundary(self):
        self.assertEqual(self.web.post('/auth/mobile/challenge',json={'password':'wrong'}).status_code,403)
        self.app.config['WTF_CSRF_ENABLED']=True
        self.assertEqual(self.web.post('/auth/mobile/challenge',json={'password':'test-password'}).status_code,400)
        with patch('auth.mobile_service.exchange_code',return_value='unknown'):
            self.assertEqual(self.mobile.post('/api/mobile/session',json={'code':'test'}).status_code,428)
        self.app.config['WECHAT_MINI_ENABLED']=False
        self.assertEqual(self.mobile.get('/api/mobile/bootstrap').status_code,404)

    def test_wechat_errors_never_expose_provider_secrets_or_accept_client_identity(self):
        with patch('auth.mobile_service.requests.get') as get:
            get.return_value.status_code=200
            get.return_value.json.return_value={'errcode':40029,'errmsg':'private-provider-message','session_key':'private-key'}
            response=self.mobile.post('/api/mobile/session',json={'code':'test'})
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private',response.get_data(as_text=True))
        self.assertEqual(self.mobile.post('/api/mobile/session',json={'code':'test','openid':'forged'}).status_code,400)
