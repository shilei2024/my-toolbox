import unittest
from tests import test_mobile_invoice_upload as fixtures
from models import ReimbursementPeriod


class MobilePeriodTests(unittest.TestCase):
    setUp = fixtures.MobileInvoiceTests.setUp
    challenge = fixtures.MobileInvoiceTests.challenge
    login = fixtures.MobileInvoiceTests.login

    def create(self, headers, **data):
        return self.mobile.post("/api/mobile/periods", json=data, headers=headers)

    def test_creates_two_month_period_and_makes_it_current(self):
        headers = self.login()
        response = self.create(headers, start_year=2026, start_month=11)
        self.assertEqual(response.status_code, 201, response.json)
        period = response.json["period"]
        self.assertEqual(
            (period["start_year"], period["start_month"], period["end_year"], period["end_month"]),
            (2026, 11, 2026, 12),
        )
        self.assertEqual(period["name"], "2026年11-12月")
        self.assertTrue(period["is_active"])
        bootstrap = self.mobile.get("/api/mobile/bootstrap", headers=headers).json
        self.assertEqual(bootstrap["periods"][0]["id"], period["id"])
        self.assertEqual(bootstrap["periods"][0]["end_month"], 12)
        with self.app.app_context():
            rows = ReimbursementPeriod.query.all()
            self.assertTrue(all(row.owner_type == "user" and row.owner_id == "1" for row in rows))
            self.assertEqual([row.id for row in rows if row.is_active], [period["id"]])

    def test_december_start_rolls_into_the_next_year(self):
        headers = self.login()
        response = self.create(headers, start_year=2026, start_month=12)
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(response.json["period"]["name"], "2026年12月-2027年1月")

    def test_duplicates_bad_months_and_unknown_fields_are_rejected(self):
        headers = self.login()
        self.assertEqual(self.create(headers, start_year=2027, start_month=3).status_code, 201)
        again = self.create(headers, start_year=2027, start_month=3)
        self.assertEqual(again.status_code, 409, again.json)
        self.assertEqual(again.json["error"], "同名周期已存在")
        exact = self.create(headers, start_year=2027, start_month=3, name="另一个名字")
        self.assertEqual(exact.status_code, 409, exact.json)
        self.assertEqual(exact.json["error"], "相同起止月份的周期已存在")
        named = self.create(headers, start_year=2027, start_month=5, name="补充周期")
        self.assertEqual(named.status_code, 201, named.json)
        self.assertEqual(self.create(headers, start_year=2027, start_month=7, name="补充周期").status_code, 409)
        self.assertEqual(self.create(headers, start_year=2027, start_month=13).status_code, 400)
        self.assertEqual(self.create(headers, start_year=2027, start_month=0).status_code, 400)
        self.assertEqual(self.create(headers, start_year="2027", start_month=3).status_code, 400)
        self.assertEqual(self.create(headers, start_year=1999, start_month=3).status_code, 400)
        self.assertEqual(self.create(headers, start_year=2027, start_month=3, owner_id="2").status_code, 400)
        anonymous = self.app.test_client(use_cookies=False)
        self.assertEqual(
            anonymous.post("/api/mobile/periods", json={"start_year": 2027, "start_month": 3}).status_code,
            401,
        )
