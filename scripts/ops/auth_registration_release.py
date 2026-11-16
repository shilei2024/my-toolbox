"""Guarded registration rollout; no Flask bootstrap or secret output."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

try:
    from . import invoice_backup as backup, invoice_release as common
except ImportError:
    import invoice_backup as backup
    import invoice_release as common

PARENT = 'c8d9e0f1a2b3'
HEAD = 'd9e0f1a2b3c4'
PASSWORD_HEAD = 'e0f1a2b3c4d5'


def versions(password_first):
    return (HEAD, PASSWORD_HEAD, 'e0f1a2b3c4d5_registration_password.py') if password_first else (
        PARENT, HEAD, 'd9e0f1a2b3c4_verified_registration.py')


def fingerprint(conn, schema, tables):
    from sqlalchemy import text
    result = {}
    for table in tables:
        # Fixed identifiers are taken from the database catalog, then quoted.
        quoted = conn.dialect.identifier_preparer.quote_identifier(table)
        expression = "to_jsonb(t) - 'registration_id'" if table == 'account_mail_jobs' else 'to_jsonb(t)'
        if table == 'account_registrations':
            expression = "to_jsonb(t) - 'password_hash'"
        result[table] = tuple(conn.execute(text(
            f'SELECT count(*),md5(COALESCE(string_agg(md5(({expression})::text),\'\' '
            f'ORDER BY md5(({expression})::text)),\'\')) FROM "{schema}".{quoted} t')).one())
    return result


def migrate(root, url, *, schema='public', password_first=False):
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    common.require(schema == 'public' or re.fullmatch(r'auth_rehearsal_[a-z0-9_]+', schema), 'invalid-schema')
    parent, target, filename = versions(password_first)
    engine = sa.create_engine(url, connect_args={'connect_timeout':10,
        'options':f'-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=300000'})
    try:
        with engine.begin() as conn:
            common.require(conn.dialect.name == 'postgresql', 'postgresql-required')
            common.require(conn.exec_driver_sql('SELECT version_num FROM alembic_version FOR UPDATE').scalars().all() == [parent], 'unexpected-parent-revision')
            conn.exec_driver_sql('LOCK TABLE users,account_mail_jobs IN SHARE ROW EXCLUSIVE MODE')
            tables = [t for t in sa.inspect(conn).get_table_names(schema=schema) if t != 'alembic_version']
            before = fingerprint(conn, schema, tables)
            spec = importlib.util.spec_from_file_location('registration_revision', root/'migrations/versions'/filename)
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            module.op = Operations(MigrationContext.configure(conn)); module.upgrade()
            conn.execute(sa.text('UPDATE alembic_version SET version_num=:revision'), {'revision':target})
            common.require(fingerprint(conn, schema, tables) == before, 'historical-data-changed')
        return target
    finally:
        engine.dispose()


def deploy(args):
    root = Path('/opt/mytoolbox')
    parent, target, _ = versions(args.password_first)
    common.require(os.name == 'posix' and os.geteuid() == 0 and Path.cwd().resolve() == root, 'server-root-required')
    common.require(args.restore_verified and args.staging_verified, 'restore-and-staging-required')
    common.require(all(re.fullmatch('[0-9a-f]{40}', v) for v in (args.source,args.target)), 'full-sha-required')
    common.require(common.git(root,'rev-parse','HEAD') == args.source, 'source-changed')
    common.require(common.git(root,'rev-parse','origin/main') == args.target, 'reviewed-main-required')
    common.require(common.git(root,'branch','--show-current') == 'main', 'main-required')
    common.require(set(common.git(root,'diff','--name-only','HEAD').splitlines()) <= {common.CADDY}, 'unexpected-changes')
    common.require(not common.git(root,'diff','--cached','--name-only'), 'staged-changes')
    common.require(not common.git(root,'diff','--name-only',args.source,args.target,'--','requirements.txt',common.CADDY), 'dependencies-or-proxy-changed')
    common.require(subprocess.run(['git','merge-base','--is-ancestor',args.source,args.target],cwd=root,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode == 0, 'not-fast-forward')
    url = backup.service_database_url(root)
    base = Path('/var/backups/mytoolbox'); base.mkdir(mode=0o700,parents=True,exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='verified-registration-',dir=base))
    stopped = False
    try:
        with common.release_lock(), (directory/'release.log').open('x',encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
            subprocess.run(['systemctl','stop','mytoolbox'],check=True,timeout=60)
            stopped = True
            common.require(subprocess.run(['systemctl','is-active','--quiet','mytoolbox']).returncode != 0, 'service-still-active')
            protected = {n:common.file_digest(root/n) for n in ('.env',common.CADDY)}
            metadata = backup.backup(root,directory,url)
            common.require(metadata['migration_revisions'] == [parent], 'unexpected-revision')
            metadata.update(target_commit=args.target,purpose='verified-registration-final',restore_verified_by_operator=True,staging_verified_by_operator=True)
            backup.private_manifest(directory,metadata)
            common.checkout_release(root,args.target,log)
            common.require(all(common.file_digest(root/n) == v for n,v in protected.items()), 'configuration-changed')
            migrate(root,url,password_first=args.password_first)
            subprocess.run(['systemctl','start','mytoolbox'],check=True,timeout=60)
            import requests
            import time
            for _ in range(20):
                try:
                    response = requests.get('https://mindfulpenpal.com/healthz', timeout=(3,5),allow_redirects=False)
                    if response.status_code == 200 and response.json().get('status') == 'ok': break
                except (requests.RequestException,ValueError): pass
                time.sleep(2)
            else: raise RuntimeError('health-failed')
        backup.private_manifest(directory,metadata)
        print('REGISTRATION_RELEASE_OK')
        print('revision='+target)
        print('release_commit='+args.target)
        print('backup_dir='+str(directory))
    except BaseException:
        if stopped:
            subprocess.run(['systemctl','stop','mytoolbox'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        print('private_backup_dir='+str(directory))
        raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action',required=True)
    rehearsal = sub.add_parser('rehearse')
    rehearsal.add_argument('--backup-manifest',required=True)
    rehearsal.add_argument('--writers-stopped',action='store_true')
    rehearsal.add_argument('--password-first',action='store_true')
    production = sub.add_parser('deploy')
    production.add_argument('--source',required=True)
    production.add_argument('--target',required=True)
    production.add_argument('--restore-verified',action='store_true')
    production.add_argument('--staging-verified',action='store_true')
    production.add_argument('--password-first',action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'deploy':
            deploy(args)
        else:
            from sqlalchemy.engine import make_url
            root = Path(__file__).resolve().parents[2]
            sys.path.insert(0,str(root))
            from scripts.ops.auth_migration import verified_backup
            url = os.environ.get('AUTH_MIGRATION_DATABASE_URL','')
            parsed = make_url(url)
            common.require(args.writers_stopped and parsed.get_backend_name() == 'postgresql'
                and re.fullmatch(r'auth_rehearsal_[a-z0-9_]{1,40}',parsed.database or ''), 'isolated-stopped-database-required')
            verified_backup(args.backup_manifest)
            revision = migrate(root,url,password_first=args.password_first)
            print('REGISTRATION_REHEARSAL_OK revision='+revision)
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc,common.ReleaseFailure) and re.fullmatch(r'[a-z0-9-]+',str(exc)) else 'unexpected-error'
        print('REGISTRATION_RELEASE_FAILED reason='+reason+'; stop and inspect privately; do not downgrade or clear data')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
