"""In-process candidate API acceptance on the exact f5 restored database only.

No app/config import, listener or actual WeChat call. The provider exchange is
replaced by synthetic identities ONLY in this isolated test-client process.
"""
import io
import os
from pathlib import Path
import secrets
import sys
import tempfile
from unittest.mock import patch

VERIFY_DATABASE = 'mytoolbox_invoice_verify_20261028_111850'
REVISION = 'f5a6b7c8d9e0'


class CheckFailure(Exception):
    pass


def require(condition, label):
    if not condition:
        raise CheckFailure(label)


def snapshot(db, baseline=None):
    from sqlalchemy import text
    result={}
    for table in ('users','reimbursement_invoices','reimbursement_attachments'):
        rows=db.session.execute(text(f'SELECT id, md5(to_jsonb(t)::text) FROM public.{table} t')).all()
        result[table]={key:value for key,value in rows if baseline is None or key in baseline[table]}
    return result


def exercise(app):
    from extensions import db
    from models import User, UsageLog, ReimbursementInvoice, UserToolGrant
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    from auth.mobile_models import MobileSession

    def call(client, method, path, status=200, **kwargs):
        response=getattr(client,method)(path,**kwargs)
        require(response.status_code==status,f'request:{path}:expected-{status}:got-{response.status_code}')
        return response

    def account():
        password=secrets.token_urlsafe(24)
        with app.app_context():
            user=User(email='mobile-stage-'+secrets.token_hex(12)+'@example.invalid')
            user.set_password(password)
            db.session.add(user);db.session.flush()
            db.session.add(UserToolGrant(user_id=user.id,tool_id='reimbursement'))
            db.session.commit()
            user_id=user.id
        web=app.test_client()
        with web.session_transaction() as session:
            session['_user_id']=str(user_id);session['_fresh']=True
        challenge=call(web,'post','/auth/mobile/challenge',json={'password':password}).json['binding_code']
        mobile=app.test_client(use_cookies=False)
        # Never requests a real identity or stores any real WeChat secret.
        with patch('auth.mobile_service.exchange_code',return_value='stage-'+secrets.token_hex(16)):
            signed=call(mobile,'post','/api/mobile/session',json={'code':'synthetic-code','binding_code':challenge})
        require('Set-Cookie' not in signed.headers,'login-issued-cookie')
        token=signed.json['access_token']
        headers={'Authorization':'Bearer '+token}
        return user_id,password,web,mobile,headers,token

    user_id,password,web,mobile,headers,token=account()
    data=call(web,'get','/tools/reimbursement/api/bootstrap').json
    office=data['offices'][0]['id']
    period=call(web,'post','/tools/reimbursement/api/periods',201,json={
        'start_year':2026,'start_month':6,'end_year':2026,'end_month':7}).json['period']['id']
    call(web,'put',f'/tools/reimbursement/api/aux/{period}',json={'vehicle':[{'date':'2026-06-01','km_total':10}]})
    before=call(web,'get',f'/tools/reimbursement/api/summary/{period}').json
    require(before['summary']['total_amount']==10,'fixture-mileage-total')

    def image():
        stream=io.BytesIO();metadata=PngInfo();metadata.add_text('fixture',secrets.token_hex(16))
        Image.new('RGB',(12,12),'white').save(stream,'PNG',pnginfo=metadata)
        return stream.getvalue()

    def upload(content,key,kind='fuel'):
        return mobile.post('/api/mobile/invoices',headers=headers,data={
            'file':(io.BytesIO(content),'stage-receipt.png'),'period_id':str(period),'office_id':str(office),
            'document_kind':kind,'occurrence_month':'2026-08','idempotency_key':key})

    original=image();key=secrets.token_hex(16)
    first=upload(original,key)
    require(first.status_code==201,'upload-not-created')
    require('Set-Cookie' not in first.headers,'upload-issued-cookie')
    invoice=first.json['invoice']
    require(invoice['inclusion_policy']=='retain' and invoice['occurrence_month']=='2026-08','cross-period-retention')
    retry=upload(original,key)
    require(retry.status_code==200 and retry.json['invoice']['id']==invoice['id'],'retry-not-idempotent')
    require(upload(original,key,'toll').status_code==409,'changed-intent-accepted')
    ordinary=upload(image(),secrets.token_hex(16),'invoice')
    require(ordinary.status_code==201 and ordinary.json['invoice']['inclusion_policy']=='review','ordinary-invoice-not-review')
    after=call(web,'get',f'/tools/reimbursement/api/summary/{period}').json
    require(after['summary']['total_amount']==before['summary']['total_amount'],'retained-invoice-changed-expenses')
    require(after['aux']==before['aux'],'upload-changed-mileage')
    listing=call(mobile,'get',f'/api/mobile/invoices?period_id={period}',headers=headers).json
    require(len(listing['invoices'])==2,'mobile-list-not-shared')
    content=call(mobile,'get',invoice['file_endpoint'],headers=headers)
    require(content.data==original and 'no-store' in content.headers.get('Cache-Control',''),'original-not-preserved')
    call(web,'get','/api/mobile/bootstrap',401,headers=headers)
    call(mobile,'get',f'/tools/reimbursement/api/summary/{period}',404,headers=headers)
    _,_,_,other,other_headers,_=account()
    call(other,'get',invoice['file_endpoint'],404,headers=other_headers)
    call(other,'get',f'/api/mobile/invoices?period_id={period}',404,headers=other_headers)
    with app.app_context():
        require(ReimbursementInvoice.query.filter_by(owner_type='user',owner_id=str(user_id)).count()==2,'duplicate-invoice')
        require(UsageLog.query.filter_by(user_id=user_id,tool_id='reimbursement',status='success').count()==2,'retry-charged-again')
        require(MobileSession.query.filter_by(user_id=user_id,token_hash=token).count()==0,'token-stored-in-plaintext')
    # Exercise the new entry flow on synthetic data only. Mocking the provider
    # verifies integration, never the accuracy of real images or paid OCR.
    ordinary_id=ordinary.json['invoice']['id']
    detail_path=f'/api/mobile/invoices/{ordinary_id}'
    detail=call(mobile,'get',detail_path,headers=headers).json
    with patch('tools.reimbursement.recognize_original',return_value=({'invoice_number':'stage-001',
            'seller_name':'合成测试商家','invoice_date':'2026-06-02','amount_excluding_tax':'100',
            'tax_amount':'6','total_amount':'106'},'synthetic')) as provider:
        draft=call(mobile,'post',detail_path+'/recognize',headers=headers,json={}).json
        require(draft['success'],'recognition-draft-missing')
        require(call(mobile,'post',detail_path+'/recognize',headers=headers,json={}).json['cached'],'draft-not-cached')
        require(provider.call_count==1,'duplicate-ocr-call')
    require(call(web,'get',f'/tools/reimbursement/api/summary/{period}').json['summary']==after['summary'],'draft-changed-summary')
    refs=call(mobile,'get','/api/mobile/bootstrap',headers=headers).json
    # Same organization directory and customer service as the website; all
    # records belong to this run's newly created synthetic account.
    from shared.models import Organization, OrganizationMembership
    app.config['CUSTOMER_PROJECTS_ENABLED']=True
    with app.app_context():
        organization=Organization(name='合成录入验收-'+secrets.token_hex(8))
        db.session.add(organization);db.session.flush()
        db.session.add(OrganizationMembership(organization_id=organization.id,user_id=user_id,roles_json='["sales"]'))
        db.session.commit()
    customer=call(mobile,'post','/api/mobile/customers',201,headers=headers,
        json={'name':'合成验收客户-'+secrets.token_hex(8),'short_name':'验收客户简称','grade':'AA'}).json['customer']
    parity_refs=call(mobile,'get','/api/mobile/bootstrap',headers=headers).json
    site_refs=call(web,'get','/tools/reimbursement/api/bootstrap').json
    require(parity_refs['customers']==site_refs['customers'],'customer-directory-mismatch')
    values={**draft['draft'],'confirmed':True,'snapshot':detail['snapshot'],'inclusion_policy':'expense',
        'customer_id':customer['id'],'customer_level':'AAA',
        'category_id':next(c['id'] for c in refs['categories'] if c['name']=='办公费'),
        'product_line_id':refs['product_lines'][0]['id']}
    confirmed=call(mobile,'post',detail_path+'/confirm',headers=headers,json=values).json
    require(confirmed['invoice']['amount_confirmed'],'not-confirmed')
    require(confirmed['invoice']['customer_level']=='AA','customer-grade-not-canonical')
    call(mobile,'post',detail_path+'/confirm',409,headers=headers,json=values)
    values.update(snapshot=confirmed['snapshot'],category_id=refs['categories'][0]['id'],
        linked_detail={'date':'2026-06-02','category':'礼品','place':'验收地点','participants':'验收参与人',
            'amount':'50','purpose':'验收事由','approval':'验收审批'})
    linked=call(mobile,'post',detail_path+'/confirm',headers=headers,json=values).json['invoice']['linked_detail']
    require(linked['participants']=='验收参与人' and linked['customer']=='验收客户简称','linked-detail-not-shared')
    dispatch_path=f'/api/mobile/dispatch/{period}'
    state=call(mobile,'get',dispatch_path,headers=headers).json
    rows=state['rows']+[{'id':None,'date':'2026-06-02','from_location':'测试起点','to_location':'测试终点',
        'contact':'合成联系人','km_total':'20','toll_fee':'5','parking_fee':'2','product_line':refs['product_lines'][0]['name']}]
    saved=call(mobile,'put',dispatch_path,headers=headers,json={'snapshot':state['snapshot'],'rows':rows}).json
    require(len(saved['rows'])==2,'vehicle-save-missing')
    call(mobile,'put',dispatch_path,409,headers=headers,json={'snapshot':state['snapshot'],'rows':[]})
    dashboard=call(mobile,'get',f'/api/mobile/dashboard/{period}',headers=headers).json
    site=call(web,'get',f'/tools/reimbursement/api/summary/{period}').json
    require(float(dashboard['total_amount'])==site['summary']['total_amount'],'dashboard-summary-mismatch')
    require(float(dashboard['km_total'])==30,'actual-mileage-changed')
    exported=call(web,'get',f'/tools/reimbursement/api/export/details/{period}')
    import xlrd
    book=xlrd.open_workbook(file_contents=exported.data)
    require(any('测试起点' in str(sheet.cell_value(r,c)) for sheet in book.sheets()
        for r in range(sheet.nrows) for c in range(sheet.ncols)),'dispatch-not-in-excel')
    require(any('验收参与人' in str(sheet.cell_value(r,c)) for sheet in book.sheets()
        for r in range(sheet.nrows) for c in range(sheet.ncols)),'linked-detail-not-in-excel')
    call(other,'get',detail_path,404,headers=other_headers)
    call(other,'get',dispatch_path,404,headers=other_headers)
    call(other,'get',f'/api/mobile/dashboard/{period}',404,headers=other_headers)
    print('MOBILE_ENTRY_SMOKE_OK: draft, cache, confirm, stale-write, dispatch, dashboard, Excel, isolation')
    print('MOBILE_FORM_PARITY_OK: customer-directory, create, grade, linked-details, website, Excel')
    identity=call(web,'get','/auth/mobile/bindings').json['bindings'][0]['id']
    call(web,'delete',f'/auth/mobile/bindings/{identity}',json={'password':password})
    call(mobile,'get','/api/mobile/bootstrap',401,headers=headers)
    print('MOBILE_API_SMOKE_OK: binding, upload, retry, website, mileage, original, isolation, revoke')


def main():
    require(len(sys.argv)==2,'candidate-directory-required')
    root=Path(sys.argv[1]).resolve(strict=True)
    require(not (root/'.env').exists(),'candidate-must-not-have-dotenv')
    require((root/'auth/mobile_routes.py').is_file(),'mobile-candidate-required')
    require(os.name=='posix' and os.geteuid()!=0,'run-as-postgres-not-root')
    os.chdir(root);sys.path.insert(0,str(root))
    from flask import Flask
    from sqlalchemy import text
    from extensions import db,csrf,limiter,login_manager
    from models import User
    from auth.mobile_routes import binding_bp,mobile_bp
    from tools.reimbursement import tool_bp
    with tempfile.TemporaryDirectory(prefix='mobile-smoke-') as uploads:
        app=Flask(__name__,root_path=str(root))
        app.config.update(TESTING=True,SECRET_KEY=secrets.token_urlsafe(32),SESSION_PROTECTION=None,
            SQLALCHEMY_DATABASE_URI=f'postgresql+psycopg2://postgres@/{VERIFY_DATABASE}?host=/var/run/postgresql&port=5432',
            WTF_CSRF_ENABLED=False,RATELIMIT_ENABLED=False,UPLOAD_DIR=uploads,DAILY_FREE_LIMIT=100,ANON_FREE_LIMIT=10,
            WECHAT_MINI_ENABLED=True,WECHAT_MINI_APP_ID='wxe79848a64a839db8',WECHAT_MINI_APP_SECRET='synthetic-staging-only-not-a-secret')
        db.init_app(app);csrf.init_app(app);limiter.init_app(app);login_manager.init_app(app)
        login_manager.user_loader(lambda uid:db.session.get(User,int(uid)))
        app.register_blueprint(binding_bp);app.register_blueprint(mobile_bp)
        app.register_blueprint(tool_bp,url_prefix='/tools/reimbursement')
        with app.app_context():
            require(db.session.execute(text('SELECT current_database()')).scalar()==VERIFY_DATABASE,'wrong-database')
            require(db.session.execute(text('SELECT version_num FROM public.alembic_version')).scalars().all()==[REVISION],'wrong-revision')
            before=snapshot(db)
        try:
            exercise(app)
        finally:
            with app.app_context():
                db.session.rollback()
                require(snapshot(db,before)==before,'historical-data-changed')
        print('MOBILE_HISTORY_OK: existing users, invoices and original BLOBs unchanged')
        print('MOBILE_STAGING_SMOKE_OK')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        label=str(exc) if isinstance(exc,CheckFailure) else 'unexpected-error'
        print('MOBILE_STAGING_SMOKE_FAILED: '+label+'; stop release',file=sys.stderr)
        sys.exit(1)
