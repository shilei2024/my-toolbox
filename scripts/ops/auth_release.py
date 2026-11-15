"""Operator-run guarded PostgreSQL auth rollout. No secrets in console output.

Copy this and invoice_backup.py/invoice_release.py outside the checkout first.
Requires exact fetched main SHA and explicit restore/staging acknowledgement.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import json
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

HEAD = "c8d9e0f1a2b3"
PARENT = "f5a6b7c8d9e0"
MIGRATIONS = (
    ("a6b7c8d9e0f1", "a6b7c8d9e0f1_unified_identity_compat.py"),
    ("b7c8d9e0f1a2", "b7c8d9e0f1a2_unified_auth_sessions.py"),
    (HEAD, "c8d9e0f1a2b3_account_email_registration.py"),
)


def history(conn, schema="public"):
    from sqlalchemy import text
    expressions = {
        "users": "to_jsonb(t) - ARRAY['email_verified_at','auth_epoch','updated_at']",
        "reimbursement_invoices": "to_jsonb(t)",
        "reimbursement_attachments": "to_jsonb(t)",
        "account_mobile_sessions": "to_jsonb(t) - 'auth_epoch'",
        "account_binding_challenges": "to_jsonb(t) - ARRAY['source_session_hash','auth_epoch','prepared_subject','confirmation_hash']",
    }
    return {table:tuple(conn.execute(text(
        f'SELECT count(*),md5(COALESCE(string_agg(md5(({expr})::text),\'\' ORDER BY t.id),\'\')) FROM "{schema}".{table} t'
    )).one()) for table,expr in expressions.items()}


def migrate(root, url, *, schema="public"):
    """One transaction, no Flask bootstrap, no implicit seeds or business writes."""
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    sys.path.insert(0,str(root))
    from auth.identity_migration import preflight, backfill
    common.require(schema == "public" or re.fullmatch(r"auth_rehearsal_[a-z0-9_]+", schema), "invalid-schema")
    engine=sa.create_engine(url,connect_args={"connect_timeout":10,"options":f"-csearch_path={schema} -clock_timeout=15000 -cstatement_timeout=300000"})
    try:
        with engine.begin() as conn:
            common.require(conn.dialect.name=="postgresql","postgresql-required")
            version=conn.execute(sa.text("SELECT version_num FROM alembic_version FOR UPDATE")).scalars().all()
            common.require(version==[PARENT],"expected-unified-auth-not-yet-installed")
            conn.exec_driver_sql("LOCK TABLE users,account_external_identities,account_mobile_sessions,account_binding_challenges IN SHARE ROW EXCLUSIVE MODE")
            common.require(preflight(conn)["ready"],"legacy-account-audit-failed")
            before=history(conn, schema)
            for revision,filename in MIGRATIONS:
                spec=importlib.util.spec_from_file_location("auth_release_revision",root/"migrations/versions"/filename)
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                module.op=Operations(MigrationContext.configure(conn));module.upgrade()
                if revision=="a6b7c8d9e0f1":backfill(conn)
                conn.execute(sa.text("UPDATE alembic_version SET version_num=:revision"),{"revision":revision})
            common.require(history(conn, schema)==before,"historical-data-changed")
        return HEAD
    finally:engine.dispose()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target",required=True)
    parser.add_argument("--source",required=True)
    parser.add_argument("--restore-verified",action="store_true")
    parser.add_argument("--staging-verified",action="store_true")
    args=parser.parse_args()
    os.umask(0o077)
    root=Path("/opt/mytoolbox")
    stage="preflight";stopped=False;directory=None
    try:
        common.require(os.name=="posix" and os.geteuid()==0 and Path.cwd().resolve()==root,"server-root-and-checkout-required")
        common.require(args.restore_verified and args.staging_verified,"restore-and-staging-evidence-required")
        common.require(all(re.fullmatch(r"[0-9a-f]{40}",v) for v in (args.source,args.target)),"full-sha-required")
        common.require(common.git(root,"rev-parse","HEAD")==args.source,"source-changed")
        common.require(common.git(root,"rev-parse","origin/main")==args.target,"reviewed-main-target-required")
        common.require(common.git(root,"branch","--show-current")=="main","main-required")
        common.require(set(common.git(root,"diff","--name-only","HEAD").splitlines()) <= {common.CADDY},"unexpected-tracked-changes")
        common.require(not common.git(root,"diff","--cached","--name-only"),"staged-changes")
        common.require(not common.git(root,"diff","--name-only",args.source,args.target,"--",common.CADDY,"requirements.txt"),"proxy-or-dependencies-need-separate-review")
        # The source service must still run here; credentials are read privately.
        url=backup.service_database_url(root)
        base=Path("/var/backups/mytoolbox");base.mkdir(mode=0o700,parents=True,exist_ok=True)
        directory=Path(tempfile.mkdtemp(prefix="unified-auth-final-",dir=base))
        with common.release_lock(), (directory/"release.log").open("x",encoding="utf-8") as log, redirect_stdout(log),redirect_stderr(log):
            stage="stop"
            subprocess.run(["systemctl","stop","mytoolbox"],check=True,timeout=60)
            stopped=True
            common.require(subprocess.run(["systemctl","is-active","--quiet","mytoolbox"]).returncode!=0,"service-still-active")
            stage="backup"
            protected={name:common.file_digest(root/name) for name in (".env",common.CADDY)}
            metadata=backup.backup(root,directory,url)
            common.require(metadata["migration_revisions"]==[PARENT],"unexpected-production-revision")
            metadata.update(target_commit=args.target,purpose="unified-auth-final-stopped",restore_verified_by_operator=True,staging_verified_by_operator=True)
            backup.private_manifest(directory,metadata)
            stage="checkout"
            common.checkout_release(root,args.target,log)
            common.require(all(common.file_digest(root/name)==value for name,value in protected.items()),"configuration-changed")
            stage="migration"
            migrate(root,url)
            stage="restart"
            subprocess.run(["systemctl","start","mytoolbox"],check=True,timeout=60)
            stage="health"
            import requests
            import time
            for attempt in range(20):
                try:
                    response=requests.get("https://mindfulpenpal.com/healthz",timeout=(3,5),allow_redirects=False)
                    if response.status_code==200 and response.json().get("status")=="ok":break
                except (requests.RequestException,ValueError):pass
                time.sleep(2)
            else:raise RuntimeError("health-failed")
        backup.private_manifest(directory, metadata)
        print("AUTH_RELEASE_OK")
        print("release_commit="+args.target)
        print("revision="+HEAD)
        print("backup_dir="+str(directory))
        return 0
    except BaseException:
        # Do not auto-start old code after new credential semantics were committed.
        if stopped:subprocess.run(["systemctl","stop","mytoolbox"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        print("AUTH_RELEASE_FAILED stage="+stage+"; do not reset database or checkout old auth code")
        if directory:print("private_backup_dir="+str(directory))
        return 1


if __name__=="__main__":raise SystemExit(main())
