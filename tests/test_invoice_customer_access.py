"""Ordinary invoice users share a private customer directory across both clients."""
import unittest

import xlrd
from extensions import db
from models import User, UserToolGrant
from shared.models import AuditEvent, Organization, OrganizationMembership
from customer_projects.models import Customer
from customer_projects.permissions import module_available
from tests import test_mobile_recognition as fixtures


class InvoiceCustomerAccessTests(unittest.TestCase):
    setUp = fixtures.RecognitionTests.setUp
    challenge = fixtures.RecognitionTests.challenge
    login = fixtures.RecognitionTests.login
    upload = fixtures.RecognitionTests.upload
    prepare = fixtures.RecognitionTests.prepare
    values = fixtures.RecognitionTests.values

    def test_ordinary_user_without_organization_creates_from_both_clients_and_exports(self):
        headers, invoice_id = self.prepare()
        self.app.config.update(CUSTOMER_PROJECTS_ENABLED=False,
                               CUSTOMER_PROJECTS_PILOT_EMAILS="another@example.test")
        for response in (self.web.get('/tools/reimbursement/api/bootstrap'),
                         self.mobile.get('/api/mobile/bootstrap', headers=headers)):
            self.assertTrue(response.json['customer_creation_enabled'])
            self.assertEqual(response.json['customers'], [])
        with self.app.app_context():
            self.assertFalse(db.session.get(User, 1).is_admin)
            self.assertEqual(Organization.query.count(), 0)  # GET has no provisioning side effect.
        web_created = self.web.post('/tools/reimbursement/api/customers',
                                    json={'name': '个人客户全名', 'short_name': '个人简称', 'grade': 'AA'})
        self.assertEqual(web_created.status_code, 201, web_created.json)
        customer = web_created.json['customer']
        mobile_created = self.mobile.post('/api/mobile/customers', headers=headers,
                                         json={'name': '手机新增客户', 'grade': 'A'})
        self.assertEqual(mobile_created.status_code, 201, mobile_created.json)
        mobile_refs = self.mobile.get('/api/mobile/bootstrap', headers=headers).json
        web_refs = self.web.get('/tools/reimbursement/api/bootstrap').json
        self.assertEqual(mobile_refs['customers'], web_refs['customers'])
        self.assertEqual(len(mobile_refs['customers']), 2)
        with self.app.app_context():
            self.assertEqual(Organization.query.count(), 1)
            self.assertEqual(OrganizationMembership.query.count(), 0)
            self.assertEqual(AuditEvent.query.filter_by(object_type='customer', action='created').count(), 2)
        with self.app.test_request_context():
            from flask_login import login_user
            login_user(db.session.get(User, 1))
            self.app.config.update(CUSTOMER_PROJECTS_ENABLED=True, CUSTOMER_PROJECTS_PILOT_EMAILS='')
            self.assertFalse(module_available())
        body = self.values(headers, invoice_id, 'expense')
        body.update(customer_id=customer['id'], customer_level='AAA',
                    category_id=mobile_refs['categories'][0]['id'])
        saved = self.mobile.post(f'/api/mobile/invoices/{invoice_id}/confirm', headers=headers, json=body)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json['invoice']['customer_level'], 'AA')
        self.assertEqual(saved.json['invoice']['linked_detail']['customer'], '个人简称')
        website = self.web.get('/tools/reimbursement/api/invoices').json['invoices'][0]
        self.assertEqual(website['customer']['id'], customer['id'])
        self.assertEqual(website['customer_level'], 'AA')
        exported = self.web.get(f'/tools/reimbursement/api/export/details/{self.period}')
        self.assertEqual(exported.status_code, 200)
        book = xlrd.open_workbook(file_contents=exported.data)
        cells = [str(sheet.cell_value(r, c)) for sheet in book.sheets()
                 for r in range(sheet.nrows) for c in range(sheet.ncols)]
        self.assertIn('个人简称', cells)

    def test_private_customer_survives_joining_organization_without_granting_crm_access(self):
        customer = self.web.post('/tools/reimbursement/api/customers', json={'name': '本人客户'}).json['customer']
        with self.app.app_context():
            organization = Organization(name='后来加入的组织')
            db.session.add(organization)
            db.session.flush()
            db.session.add(OrganizationMembership(organization_id=organization.id, user_id=1, roles_json='["fae"]'))
            db.session.commit()
        headers = self.login()
        created = self.mobile.post('/api/mobile/customers', headers=headers, json={'name': 'FAE个人客户'})
        self.assertEqual(created.status_code, 201, created.json)
        listed = self.web.get('/tools/reimbursement/api/bootstrap').json['customers']
        self.assertEqual({c['id'] for c in listed}, {customer['id'], created.json['customer']['id']})
        with self.app.app_context():
            self.assertEqual(OrganizationMembership.query.one().roles, frozenset({'fae'}))
            self.assertEqual(len({row.organization_id for row in Customer.query.all()}), 1)

    def test_cross_account_selection_and_forged_ownership_are_rejected(self):
        customer = self.web.post('/tools/reimbursement/api/customers', json={'name': '甲私有'}).json['customer']
        with self.web.session_transaction() as session:
            session['_user_id'] = '2'
        refs = self.web.get('/tools/reimbursement/api/bootstrap').json
        self.office = refs['offices'][0]['id']
        self.period = self.web.post('/tools/reimbursement/api/periods', json={
            'start_year': 2026, 'start_month': 6, 'end_year': 2026, 'end_month': 7,
        }).json['period']['id']
        headers, invoice_id = self.prepare()
        refs = self.mobile.get('/api/mobile/bootstrap', headers=headers).json
        self.assertEqual(refs['customers'], [])
        body = self.values(headers, invoice_id)
        body.update(customer_id=customer['id'])
        self.assertEqual(self.mobile.post(f'/api/mobile/invoices/{invoice_id}/confirm',
                                         headers=headers, json=body).status_code, 400)
        for payload in ({'name': '伪造', 'primary_owner_user_id': 1},
                        {'name': '伪造', 'organization_id': 'not-mine'}):
            self.assertEqual(self.web.post('/tools/reimbursement/api/customers', json=payload).status_code, 400)
            self.assertEqual(self.mobile.post('/api/mobile/customers', headers=headers, json=payload).status_code, 400)

    def test_denied_and_invalid_requests_never_provision_customer_space(self):
        headers = self.login()
        for payload in ([], {'name': ''}, {'name': None}, {'name': 'bad', 'grade': 'B'},
                        {'name': ['bad']}, {'name': 'x' * 256}):
            for response in (self.web.post('/tools/reimbursement/api/customers', json=payload),
                             self.mobile.post('/api/mobile/customers', headers=headers, json=payload)):
                self.assertEqual(response.status_code, 400, response.json)
        with self.app.app_context():
            self.assertEqual(Organization.query.count(), 0)
            db.session.delete(db.session.get(UserToolGrant, {'user_id': 1, 'tool_id': 'reimbursement'}))
            db.session.commit()
        self.assertFalse(self.web.get('/tools/reimbursement/api/bootstrap').json['customer_creation_enabled'])
        self.assertEqual(self.web.post('/tools/reimbursement/api/customers', json={'name': '无授权'}).status_code, 403)
        self.assertEqual(self.mobile.post('/api/mobile/customers', headers=headers, json={'name': '无授权'}).status_code, 403)
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post('/tools/reimbursement/api/customers', json={'name': '匿名'}).status_code, 403)
        with self.app.app_context():
            self.assertEqual(Organization.query.count(), 0)
            self.assertEqual(Customer.query.count(), 0)

    def test_admin_without_organization_and_disabled_account(self):
        with self.app.app_context():
            user = db.session.get(User, 1)
            user.is_admin = True
            db.session.delete(db.session.get(UserToolGrant, {'user_id': 1, 'tool_id': 'reimbursement'}))
            db.session.commit()
        self.assertEqual(self.web.post('/tools/reimbursement/api/customers', json={'name': '管理账号个人客户'}).status_code, 201)
        with self.app.app_context():
            db.session.get(User, 1).is_active_user = False
            db.session.commit()
        self.assertEqual(self.web.post('/tools/reimbursement/api/customers', json={'name': '已禁用'}).status_code, 403)

    def test_crm_bootstrap_never_reuses_a_personal_container(self):
        self.assertEqual(self.web.post('/tools/reimbursement/api/customers', json={'name': '个人客户'}).status_code, 201)
        from customer_projects.services.projects import bootstrap_organization
        with self.app.app_context():
            personal = Organization.query.one()
            self.assertEqual(personal.status, 'personal')
            team = bootstrap_organization('真正的业务团队', 1)
            self.assertNotEqual(team.id, personal.id)
            self.assertEqual(OrganizationMembership.query.filter_by(organization_id=personal.id).count(), 0)
            self.assertEqual(Customer.query.one().organization_id, personal.id)
