"""Provision one isolated ordinary review user; credentials stay on the server."""
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import re
import sys
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo


def require(condition, label):
    if not condition:
        raise RuntimeError(label)


def create_synthetic_account(email, password):
    """Only inserts new owned rows. Caller controls the single transaction."""
    from extensions import db
    from models import (User, UserToolGrant, Tool, ReimbursementPeriod, ReimbursementOffice,
        ReimbursementCategory, ReimbursementProductLine, ReimbursementInvoice, ReimbursementAuxDetail)
    from shared.models import Organization, OrganizationMembership
    from customer_projects.models import Customer
    from auth.mobile_service import audit
    from tools.reimbursement.manager import DEFAULT_CATEGORIES, DEFAULT_OFFICES
    from tools.reimbursement.attachments import PreparedOriginal, persist_original
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    require(User.query.filter_by(email=email).first() is None, "account-already-exists")
    require(db.session.get(Tool, "reimbursement") is not None, "tool-missing")
    user=User(email=email, nickname="审核演示账号",is_admin=False,is_active_user=True,
        plan="free",custom_limits=json.dumps({"reimbursement":40}))
    user.set_password(password)
    db.session.add(user);db.session.flush()
    owner={"owner_type":"user","owner_id":str(user.id)}
    db.session.add(UserToolGrant(user_id=user.id,tool_id="reimbursement"))
    organization=Organization(name="审核演示独立组织（合成数据）")
    db.session.add(organization);db.session.flush()
    db.session.add(OrganizationMembership(organization_id=organization.id,user_id=user.id,roles_json='["sales"]'))
    customer=Customer(organization_id=organization.id,name="合成演示客户",short_name="演示客户",grade="AA",
        normalized_name="合成演示客户",primary_owner_user_id=user.id,created_by_user_id=user.id,updated_by_user_id=user.id)
    db.session.add(customer)
    offices=[ReimbursementOffice(**owner,name=name,sort_order=(index+1)*10) for index,name in enumerate(DEFAULT_OFFICES)]
    categories=[ReimbursementCategory(**owner,name=name,export_key=key,color=color,sort_order=(index+1)*10)
        for index,(name,key,color) in enumerate(DEFAULT_CATEGORIES)]
    line=ReimbursementProductLine(**owner,name="演示产品线",code="DEMO-01",office="")
    now=datetime.now(ZoneInfo("Asia/Shanghai"))
    period=ReimbursementPeriod(**owner,name=f"{now.year}-{now.month:02d} 审核演示",start_year=now.year,
        start_month=now.month,end_year=now.year,end_month=now.month,is_active=True,
        employee_name="演示人员",department="演示部门",office=DEFAULT_OFFICES[0])
    db.session.add_all([*offices,*categories,line,period]);db.session.flush()
    raw=io.BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    canvas=Canvas(raw);canvas.setFont("STSong-Light",16)
    for index,text in enumerate(["合成测试票据（非真实发票，仅功能演示）", "销售方：演示商家",
            f"开票日期：{now.year}-{now.month:02d}-01", "不含税金额：100.00", "税额：6.00", "价税合计：106.00"]):
        canvas.drawString(40,780-index*40,text)
    canvas.save();content=raw.getvalue()
    attachment,_=persist_original(PreparedOriginal("合成演示票据.pdf",".pdf",content,hashlib.sha256(content).hexdigest()),**owner)
    invoice=ReimbursementInvoice(**owner,period_id=period.id,category_id=next(c.id for c in categories if c.export_key=="office_supplies"),
        office=offices[0].name,product_line=line.name,product_line_code=line.code,customer_id=customer.id,customer_level="AA",
        vendor="演示商家",description="合成测试票据，非真实发票",invoice_date=now.date().replace(day=1),
        amount=100,tax_amount=6,total_amount=106,amount_confirmed=False,inclusion_policy="review",document_kind="invoice",
        file_url="/tools/reimbursement/preview/"+attachment.stored_name,file_name=attachment.original_name,file_size=len(content))
    db.session.add(invoice)
    db.session.add(ReimbursementAuxDetail(**owner,period_id=period.id,kind="vehicle",sort_order=0,data_json=json.dumps({
        "date":now.date().replace(day=1).isoformat(),"from_location":"演示起点","to_location":"演示终点",
        "contact":"演示联系人","km_total":20,"toll_fee":5,"parking_fee":2,"product_line":line.name},ensure_ascii=False)))
    db.session.flush()
    audit(user.id,"review_account.created",organization_id=organization.id)
    return {"user_id":user.id,"organization_id":organization.id,"period_id":period.id,"invoice_id":invoice.id}


def private_record(path, data, *, initial=False):
    """Atomic 0600 file replacement; never follows an existing credential link."""
    require(not path.is_symlink(),"credential-symlink-refused")
    if initial:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    else:
        fd,name=tempfile.mkstemp(prefix=".credentials-",dir=path.parent)
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
        os.chmod(name,0o600);os.replace(name,path)


def provision(app, path):
    from extensions import db
    from models import User, UserToolGrant
    from shared.models import OrganizationMembership
    path=Path(path)
    require(not path.is_symlink(),"credential-symlink-refused")
    if path.exists():
        require(os.name!="posix" or (path.stat().st_uid==os.geteuid() and path.stat().st_mode&0o077==0),"credential-permissions-invalid")
        record=json.loads(path.read_text(encoding="utf-8"))
    else:
        record={"status":"pending","email":"mini-review-"+secrets.token_hex(8)+"@mindfulpenpal.com",
            "password":secrets.token_urlsafe(24)}
        private_record(path,record,initial=True)
    require(isinstance(record,dict) and re.fullmatch(r"mini-review-[0-9a-f]{16}@mindfulpenpal\.com",str(record.get("email","")))
        and isinstance(record.get("password"),str) and len(record["password"])==32
        and record.get("status") in {"pending","ready"},"invalid-private-record")
    with app.app_context():
        user=User.query.filter_by(email=record["email"]).first()
        if user:
            require(record.get("user_id")==user.id and user.is_active_user and not user.is_admin
                and user.check_password(record["password"]) and db.session.get(UserToolGrant,{"user_id":user.id,"tool_id":"reimbursement"})
                and OrganizationMembership.query.filter_by(user_id=user.id).count()==1
                and OrganizationMembership.query.filter_by(user_id=user.id,organization_id=record.get("organization_id"),status="active").count()==1,
                "existing-account-needs-manual-review")
        else:
            require(record.get("status")=="pending","existing-account-missing")
            record.update(create_synthetic_account(record["email"],record["password"]))
            private_record(path,record)
            db.session.commit()
        record["status"]="ready"
        private_record(path,record)
    return record["user_id"]


def main():
    try:
        require(os.name=="posix" and os.geteuid()==0,"server-root-required")
        root=Path.cwd().resolve()
        require(root==Path("/opt/mytoolbox") and len(sys.argv)==1,"production-checkout-required")
        os.umask(0o077);sys.path.insert(0,str(root))
        from scripts.ops.invoice_backup import service_database_url
        # Use the running service's configuration overrides before importing Config.
        import subprocess
        pid=subprocess.check_output(["systemctl","show","mytoolbox","-p","MainPID","--value"],text=True).strip()
        require(pid.isdigit() and int(pid)>0,"service-not-running")
        names={"WECHAT_MINI_ENABLED","WECHAT_MINI_APP_ID","WECHAT_MINI_APP_SECRET","CUSTOMER_PROJECTS_ENABLED","CUSTOMER_PROJECTS_PILOT_EMAILS"}
        env=dict(entry.split(b"=",1) for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in entry)
        for name in names:
            os.environ.pop(name,None)
            if name.encode() in env: os.environ[name]=env[name.encode()].decode()
        url=service_database_url(root)
        from config import Config
        from flask import Flask
        from extensions import db
        from auth.mobile_service import configured
        from sqlalchemy import text
        app=Flask(__name__);app.config.from_object(Config)
        app.config.update(SQLALCHEMY_DATABASE_URI=url,SQLALCHEMY_ENGINE_OPTIONS={},SECRET_KEY=secrets.token_urlsafe(32))
        db.init_app(app)
        with app.app_context():
            require(configured(),"mobile-not-enabled")
            require(db.session.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()==["f5a6b7c8d9e0"],"unexpected-schema")
        folder=Path("/root/mytoolbox-mini-review")
        require(not folder.is_symlink(),"credential-directory-symlink-refused")
        folder.mkdir(mode=0o700,exist_ok=True)
        require(folder.resolve()==folder and folder.stat().st_uid==0 and folder.stat().st_mode&0o077==0,"credential-directory-not-private")
        from scripts.ops.invoice_release import release_lock
        with release_lock():
            user_id=provision(app,folder/"credentials.json")
        print("REVIEW_ACCOUNT_OK")
        print("user_id="+str(user_id))
        print("credential_file="+str(folder/"credentials.json"))
        print("Keep credentials private; copy into WeChat review form only. Do not paste into chat.")
        print("customer_creation_available="+str(bool(app.config.get("CUSTOMER_PROJECTS_ENABLED") and not app.config.get("CUSTOMER_PROJECTS_PILOT_EMAILS"))))
        return 0
    except Exception as exc:
        label=str(exc) if isinstance(exc,RuntimeError) and re.fullmatch(r"[a-z0-9-]{1,60}",str(exc)) else "details-hidden"
        print("REVIEW_ACCOUNT_FAILED: "+label+"; no existing user credentials were changed")
        return 1


if __name__=="__main__":
    raise SystemExit(main())
