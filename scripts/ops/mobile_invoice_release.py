"""One-time e4 -> f5 deployment with mobile entry disabled. Root operator only."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import traceback

try:
    from . import invoice_release as common
    from . import invoice_backup as backup
except ImportError:
    import invoice_release as common
    import invoice_backup as backup

SOURCE='6239408f0cd7b79df484409d6ecb977c772454df'
CANDIDATE='ba06c23f8c2c61a9b35fde3399834ace7ec5551e'
OLD='e4f5a6b7c8d9'
NEW='f5a6b7c8d9e0'
require=common.require


def preflight(root,target):
    require(re.fullmatch('[0-9a-f]{40}',target),'invalid-target')
    require(common.git(root,'branch','--show-current')=='main','main-required')
    require(common.git(root,'rev-parse','HEAD')==SOURCE,'unexpected-production-sha')
    require(common.git(root,'rev-parse','origin/main')==target,'target-not-fetched-main')
    subprocess.run(['git','merge-base','--is-ancestor',CANDIDATE,target],cwd=root,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    require(set(common.git(root,'diff','--name-only','HEAD').splitlines()) <= {common.CADDY},'unexpected-local-changes')
    require(not common.git(root,'diff','--cached','--name-only'),'staged-changes')
    require(not common.git(root,'diff','--name-only',SOURCE,target,'--','requirements.txt',common.CADDY),'dependency-or-proxy-change')
    permitted={'CHANGELOG.md','scripts/ops/mobile_invoice_release.py','tests/test_mobile_invoice_release.py','tests/test_mobile_postgres.py'}
    require(all(p.startswith('docs/') or p in permitted for p in common.git(root,'diff','--name-only',CANDIDATE,target).splitlines()),'unverified-business-changes')
    require(subprocess.run(['systemctl','is-active','--quiet','mytoolbox']).returncode==0,'service-not-active')
    pid=subprocess.check_output(['systemctl','show','mytoolbox','-p','MainPID','--value'],text=True).strip()
    require(pid.isdigit() and int(pid)>0,'service-pid-unavailable')
    environment=dict(item.split(b'=',1) for item in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in item)
    from dotenv import dotenv_values
    flags=[environment.get(b'WECHAT_MINI_ENABLED',b'false').decode(),dotenv_values(root/'.env').get('WECHAT_MINI_ENABLED','false'),os.environ.get('WECHAT_MINI_ENABLED','false')]
    require(all(str(v or '').strip().lower() not in {'1','true','yes','on'} for v in flags),'disable-mobile-before-deploy')
    return {name:common.file_digest(root/name) for name in ('.env',common.CADDY)}


def history(connection):
    from sqlalchemy import text
    result={}
    for table in ('users','reimbursement_invoices','reimbursement_attachments'):
        value="to_jsonb(t) - 'content_sha256'" if table.endswith('attachments') else 'to_jsonb(t)'
        result[table]=tuple(connection.execute(text(f"SELECT count(*), md5(COALESCE(string_agg(md5(({value})::text),'' ORDER BY t.id),'')) FROM public.{table} t")).one())
    return result


def migrate(root,url):
    from flask import Flask
    from flask_migrate import Migrate,upgrade
    from sqlalchemy import text
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from extensions import db
    directory=str(root/'migrations')
    config=Config(str(root/'migrations/alembic.ini'));config.set_main_option('script_location',directory)
    require(ScriptDirectory.from_config(config).get_heads()==[NEW],'unexpected-migration-head')
    app=Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={'connect_args':{'connect_timeout':10,'options':'-c lock_timeout=15000 -c statement_timeout=120000'}})
    db.init_app(app);Migrate(app,db,directory=directory)
    with app.app_context():
        with db.engine.connect() as conn:
            require(conn.execute(text('SELECT version_num FROM public.alembic_version')).scalars().all()==[OLD],'unexpected-db-revision')
            before=history(conn)
        upgrade(directory=directory,revision=NEW)
        with db.engine.connect() as conn:
            require(conn.execute(text('SELECT version_num FROM public.alembic_version')).scalars().all()==[NEW],'migration-not-applied')
            require(history(conn)==before,'historical-data-changed')
            require(conn.execute(text('SELECT count(*) FROM public.reimbursement_attachments WHERE content_sha256 IS NOT NULL')).scalar_one()==0,'legacy-digest-changed')
        db.session.remove();db.engine.dispose()


def runtime_readable(root,log):
    user=subprocess.check_output(['systemctl','show','mytoolbox','-p','User','--value'],text=True).strip() or 'root'
    require(re.fullmatch('[a-zA-Z_][a-zA-Z0-9_-]*',user),'unexpected-service-user')
    names=['app.py','models.py','auth/mobile_routes.py','auth/mobile_models.py','auth/mobile_service.py',
        'tools/reimbursement/__init__.py','tools/reimbursement/manager.py','tools/reimbursement/attachments.py',
        'tools/reimbursement/mobile_models.py','tools/reimbursement/models.py','tools/reimbursement/retention.py','templates/profile.html']
    for name in names:
        require(subprocess.run(['sudo','-u',user,'--','test','-r',str(root/name)],stdout=log,stderr=log).returncode==0,'service-cannot-read-code')


def healthy_disabled():
    import requests
    for attempt in range(20):
        try:
            active=subprocess.run(['systemctl','is-active','--quiet','mytoolbox']).returncode==0
            local=requests.get('http://127.0.0.1:8000/healthz',timeout=(2,3),allow_redirects=False)
            public=requests.get('https://mindfulpenpal.com/healthz',timeout=(3,8),allow_redirects=False)
            mobile=requests.get('https://mindfulpenpal.com/api/mobile/bootstrap',timeout=(3,8),allow_redirects=False)
            if (active and local.status_code==200 and public.status_code==200 and public.json().get('status')=='ok'
                and mobile.status_code==404 and mobile.json().get('error')=='手机录入暂未开放'
                and 'Set-Cookie' not in mobile.headers and 'no-store' in mobile.headers.get('Cache-Control','')):
                return True
        except (requests.RequestException,ValueError,AttributeError):
            pass
        if attempt<19: time.sleep(2)
    return False


def execute(root,target,log,base=Path('/var/backups/mytoolbox')):
    protected=preflight(root,target)
    url=backup.service_database_url(root)
    base.mkdir(mode=0o700,parents=True,exist_ok=True)
    directory=Path(tempfile.mkdtemp(prefix='mobile-final-',dir=base))
    stage='stop';stopped=False
    try:
        subprocess.run(['systemctl','stop','mytoolbox'],check=True,stdout=log,stderr=log,timeout=60);stopped=True
        require(subprocess.run(['systemctl','is-active','--quiet','mytoolbox']).returncode!=0,'service-still-active')
        stage='backup'
        metadata=backup.backup(root,directory,url)
        require(metadata['migration_revisions']==[OLD],'backup-revision-not-e4')
        metadata.update(purpose='mobile final; main service stopped',target_commit=target,staging_evidence='operator MOBILE_MIGRATION_REHEARSAL_OK and MOBILE_STAGING_SMOKE_OK')
        backup.private_manifest(directory,metadata)
        require(common.git(root,'rev-parse','HEAD')==SOURCE,'source-changed-during-backup')
        stage='checkout'
        common.checkout_release(root,target,log)
        require(common.git(root,'rev-parse','HEAD')==target,'target-not-applied')
        require(all(common.file_digest(root/n)==v for n,v in protected.items()),'configuration-changed')
        stage='code-readability';runtime_readable(root,log)
        stage='migration';migrate(root,url)
        stage='start';subprocess.run(['systemctl','start','mytoolbox'],check=True,stdout=log,stderr=log,timeout=60)
        stage='health-disabled';require(healthy_disabled(),'health-or-mobile-disabled-check-failed')
        return directory
    except (Exception,SystemExit,KeyboardInterrupt):
        traceback.print_exc(file=log)
        if stopped:
            safe=False
            try:
                safe=(common.git(root,'rev-parse','HEAD')==SOURCE and set(common.git(root,'diff','--name-only','HEAD').splitlines())<={common.CADDY}
                    and not common.git(root,'diff','--cached','--name-only') and all(common.file_digest(root/n)==v for n,v in protected.items()))
            except Exception: pass
            try: subprocess.run(['systemctl','start' if safe else 'stop','mytoolbox'],stdout=log,stderr=log,timeout=60)
            except Exception: traceback.print_exc(file=log)
        raise common.ReleaseFailure(f'stage={stage}; backup_dir={directory}') from None


def main():
    os.umask(0o077)
    logpath=Path('/root')/('mobile-release-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)+'.log')
    try:
        require(os.name=='posix' and os.geteuid()==0,'server-root-required')
        require(len(sys.argv)==2 and Path.cwd().resolve()==Path('/opt/mytoolbox'),'deployment-path-and-sha-required')
        with common.release_lock(),logpath.open('x',encoding='utf-8') as log,redirect_stdout(log),redirect_stderr(log):
            directory=execute(Path.cwd().resolve(),sys.argv[1],log)
        print('MOBILE_DEPLOY_OK');print('release_commit='+sys.argv[1]);print('migration_revision='+NEW)
        print('backup_dir='+str(directory));print('service=active; HTTPS=OK; mobile=disabled')
        return 0
    except (Exception,SystemExit,KeyboardInterrupt) as exc:
        print('MOBILE_DEPLOY_FAILED: '+(str(exc) if isinstance(exc,common.ReleaseFailure) else 'preflight-or-runtime-failed'))
        if logpath.exists(): print('private_log='+str(logpath))
        return 1


if __name__=='__main__': raise SystemExit(main())
