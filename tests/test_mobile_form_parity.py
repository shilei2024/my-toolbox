import json
import unittest
from tests import test_mobile_recognition as fixtures
from extensions import db
from shared.models import Organization, OrganizationMembership
from customer_projects.models import Customer
from models import ReimbursementAuxDetail


class FormParityTests(unittest.TestCase):
    setUp = fixtures.RecognitionTests.setUp
    challenge = fixtures.RecognitionTests.challenge
    login = fixtures.RecognitionTests.login
    upload = fixtures.RecognitionTests.upload
    prepare = fixtures.RecognitionTests.prepare
    values = fixtures.RecognitionTests.values

    def customer_setup(self):
        self.app.config["CUSTOMER_PROJECTS_ENABLED"] = True
        with self.app.app_context():
            org = Organization(name="本组织")
            other = Organization(name="另一组织")
            db.session.add_all([org, other])
            db.session.flush()
            membership = OrganizationMembership(
                organization_id=org.id, user_id=1, roles_json='["sales"]'
            )
            customer = Customer(
                organization_id=org.id,
                name="客户全名",
                short_name="客户简称",
                grade="AA",
                normalized_name="客户全名",
                primary_owner_user_id=1,
                created_by_user_id=1,
                updated_by_user_id=1,
            )
            foreign = Customer(
                organization_id=other.id,
                name="不可见客户",
                grade="A",
                normalized_name="不可见客户",
                primary_owner_user_id=2,
                created_by_user_id=2,
                updated_by_user_id=2,
            )
            db.session.add_all([membership, customer, foreign])
            db.session.commit()
            return customer.id, foreign.id

    def test_customer_directory_create_permissions_and_explicit_linked_details_match_site(
        self,
    ):
        customer, foreign = self.customer_setup()
        headers, id = self.prepare()
        refs = self.mobile.get("/api/mobile/bootstrap", headers=headers).json
        self.assertEqual(
            refs["customers"],
            self.web.get("/tools/reimbursement/api/bootstrap").json["customers"],
        )
        self.assertEqual([c["id"] for c in refs["customers"]], [customer])
        self.assertTrue(refs["customer_creation_enabled"])
        body = self.values(headers, id, "expense")
        body.update(customer_id=foreign, customer_level="AAA")
        self.assertEqual(
            self.mobile.post(
                f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
            ).status_code,
            400,
        )
        body.update(
            customer_id=customer,
            customer_level="AAA",
            category_id=refs["categories"][0]["id"],
            linked_detail={
                "date": "2026-06-02",
                "category": "礼品",
                "place": "会场",
                "participants": "参与人",
                "amount": "50",
                "purpose": "手填事由",
                "approval": "已审批",
                "customer_id": foreign,
                "customer": "伪造名称",
            },
        )
        saved = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json["invoice"]["customer_level"], "AA")
        linked = saved.json["invoice"]["linked_detail"]
        self.assertEqual(
            (
                linked["customer_id"],
                linked["customer"],
                linked["amount"],
                linked["participants"],
            ),
            (customer, "客户简称", 50, "参与人"),
        )
        site = self.web.get(f"/tools/reimbursement/api/summary/{self.period}").json
        self.assertEqual(site["aux"]["entertainment"][0]["approval"], "已审批")
        created = self.mobile.post(
            "/api/mobile/customers",
            headers=headers,
            json={"name": "新客户", "short_name": "新简称", "grade": "A"},
        )
        self.assertEqual(created.status_code, 201, created.json)
        with self.app.app_context():
            member = OrganizationMembership.query.filter_by(user_id=1).one()
            member.roles_json = '["fae"]'
            db.session.commit()
        self.assertEqual(
            self.mobile.post(
                "/api/mobile/customers", headers=headers, json={"name": "越权"}
            ).status_code,
            403,
        )
        body.update(
            snapshot=saved.json["snapshot"],
            customer_id=None,
            customer_level="A",
            linked_detail=None,
        )
        cleared = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(cleared.status_code, 200, cleared.json)
        self.assertIsNone(cleared.json["invoice"]["customer_id"])
        self.assertEqual(cleared.json["invoice"]["customer_level"], "A")

    def test_travel_fields_and_invalid_detail_rollback(self):
        headers, id = self.prepare()
        refs = self.mobile.get("/api/mobile/bootstrap", headers=headers).json
        body = self.values(headers, id, "expense")
        body.update(
            category_id=refs["categories"][1]["id"],
            linked_detail={
                "date": "2026-06-01",
                "location": "出差地",
                "expense_type": "高铁",
                "amount": "88",
                "purpose": "客户拜访",
            },
        )
        for invalid in ({"amount": "NaN"}, {"date": "bad"}, {"invoice_id": 99}):
            bad = {**body, "linked_detail": {**body["linked_detail"], **invalid}}
            self.assertEqual(
                self.mobile.post(
                    f"/api/mobile/invoices/{id}/confirm", headers=headers, json=bad
                ).status_code,
                400,
            )
        result = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json["invoice"]["linked_detail"]["location"], "出差地")

    def test_invisible_customer_is_preserved_without_explicit_selection(self):
        from models import ReimbursementInvoice

        customer, foreign = self.customer_setup()
        headers, id = self.prepare()
        with self.app.app_context():
            row = db.session.get(ReimbursementInvoice, id)
            row.customer_id = foreign
            row.customer_level = "A"
            db.session.commit()
        detail = self.mobile.get(f"/api/mobile/invoices/{id}", headers=headers).json
        self.assertIsNone(detail["invoice"]["customer_id"])
        body = self.values(headers, id)
        body["remarks"] = "只改备注"
        saved = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(saved.status_code, 200, saved.json)
        with self.app.app_context():
            self.assertEqual(
                db.session.get(ReimbursementInvoice, id).customer_id, foreign
            )

    def test_retired_customer_linked_export_survives_remarks_edit(self):
        customer, foreign = self.customer_setup()
        headers, id = self.prepare()
        body = self.values(headers, id, "expense")
        refs = self.mobile.get("/api/mobile/bootstrap", headers=headers).json
        body.update(
            customer_id=customer,
            category_id=refs["categories"][0]["id"],
            linked_detail={"amount": "50", "participants": "参与人"},
        )
        first = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(first.status_code, 200, first.json)
        with self.app.app_context():
            row = db.session.get(Customer, customer)
            row.status = "inactive"
            db.session.commit()
        body = self.values(headers, id, "expense")
        body.update(
            category_id=refs["categories"][0]["id"],
            remarks="备注",
            linked_detail={
                "amount": "50",
                "participants": "参与人",
                "customer": "",
                "customer_id": None,
            },
        )
        saved = self.mobile.post(
            f"/api/mobile/invoices/{id}/confirm", headers=headers, json=body
        )
        self.assertEqual(saved.status_code, 200, saved.json)
        linked = saved.json["invoice"]["linked_detail"]
        self.assertEqual(
            (linked["customer_id"], linked["customer"]), (customer, "客户简称")
        )

    def test_website_edit_fields_are_covered_by_mobile_contract(self):
        import re
        from pathlib import Path
        from tools.reimbursement.mobile_recognition import FIELDS

        root = Path(__file__).parents[1]
        source = (root / "templates/tools/reimbursement/_body.html").read_text(
            encoding="utf-8"
        )
        payload = source.split("invoicePayload(){", 1)[1].split("},", 1)[0]
        website = set(re.findall(r"(?:[{,])([a-z_]+):", payload))
        derived = {
            "product_line",
            "product_line_code",
            "office",
            "file_url",
            "file_name",
            "file_size",
        }
        self.assertTrue(website)
        self.assertFalse(website - FIELDS - derived)
