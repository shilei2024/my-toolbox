import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from tests import test_mobile_invoice_upload as fixtures
from extensions import db
from models import User, UserToolGrant, ReimbursementAttachment
from shared.models import OrganizationMembership
from scripts.ops.mobile_review_account import provision


class ReviewAccountTests(unittest.TestCase):
    setUp=fixtures.MobileInvoiceTests.setUp
    challenge=fixtures.MobileInvoiceTests.challenge
    login=fixtures.MobileInvoiceTests.login

    def test_account_is_ordinary_isolated_and_reruns_do_not_reset_credentials(self):
        self.app.config['CUSTOMER_PROJECTS_ENABLED']=True
        path=Path(self.temp.name)/'credentials.json'
        uid=provision(self.app,path)
        record=json.loads(path.read_text(encoding='utf-8'))
        signed=self.mobile.post('/api/mobile/session/password',json={'email':record['email'],'password':record['password']})
        self.assertEqual(signed.status_code,200)
        headers={'Authorization':'Bearer '+signed.json['access_token']}
        refs=self.mobile.get('/api/mobile/bootstrap',headers=headers).json
        self.assertEqual(len(refs['customers']),1)
        self.assertEqual(refs['customers'][0]['name'],'合成演示客户')
        self.assertTrue(refs['customer_creation_enabled'])
        self.assertEqual(len(refs['periods']),1)
        summary=self.mobile.get(f"/api/mobile/dashboard/{record['period_id']}",headers=headers).json
        self.assertEqual(float(summary['km_total']),20)
        invoices=self.mobile.get(f"/api/mobile/invoices?period_id={record['period_id']}",headers=headers).json['invoices']
        self.assertEqual(len(invoices),1)
        self.assertEqual(invoices[0]['inclusion_policy'],'review')
        original=self.mobile.get(invoices[0]['file_endpoint'],headers=headers)
        self.assertTrue(original.data.startswith(b'%PDF-'))
        self.assertEqual(self.mobile.get(f'/api/mobile/invoices?period_id={self.period}',headers=headers).status_code,404)
        self.assertEqual(provision(self.app,path),uid)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['password'],record['password'])
        with self.app.app_context():
            user=db.session.get(User,uid)
            self.assertFalse(user.is_admin)
            self.assertEqual(user.plan,'free')
            self.assertEqual(user.custom_limit_map,{'reimbursement':40})
            self.assertEqual(UserToolGrant.query.filter_by(user_id=uid).count(),1)
            self.assertEqual(OrganizationMembership.query.filter_by(user_id=uid).count(),1)
            self.assertEqual(User.query.count(),3)
            self.assertEqual(ReimbursementAttachment.query.filter_by(owner_id=str(uid)).count(),1)
            self.assertTrue(db.session.get(User,1).check_password('test-password'))
        if os.name=='posix': self.assertEqual(path.stat().st_mode&0o777,0o600)
        # Admin password rotation must never be silently undone by rerunning.
        with self.app.app_context():
            db.session.get(User,uid).set_password('changed-for-test');db.session.commit()
        with self.assertRaises(RuntimeError): provision(self.app,path)

    def test_pending_file_after_commit_recovers_without_duplicate_rows(self):
        path=Path(self.temp.name)/'recover.json'
        from scripts.ops import mobile_review_account as script
        original=script.private_record
        def write(target,data,**kwargs):
            if data.get('status')=='ready':raise OSError('synthetic write failure')
            original(target,data,**kwargs)
        with patch.object(script,'private_record',side_effect=write), self.assertRaises(OSError):
            provision(self.app,path)
        pending=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(pending['status'],'pending')
        self.assertEqual(provision(self.app,path),pending['user_id'])
        with self.app.app_context(): self.assertEqual(User.query.count(),3)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['status'],'ready')
