from __future__ import annotations

import io
import json
import struct
import tempfile
import unittest
from datetime import date
from pathlib import Path

import xlrd
from flask import Blueprint, Flask
from xlrd.compdoc import CompDoc

from extensions import csrf, db, limiter, login_manager
from models import (
    ReimbursementAttachment,
    ReimbursementAuxDetail,
    ReimbursementCategory,
    ReimbursementInvoice,
    ReimbursementPeriod,
    ReimbursementProductLine,
)
from tools.reimbursement import ENTERTAINMENT_CATEGORIES, PRODUCT_LINES, tool_bp
from tools.reimbursement.manager import (
    COVER_TEMPLATE,
    DEFAULT_CATEGORIES,
    DEFAULT_OFFICES,
    DETAIL_TEMPLATE,
    _build_cover_xls,
    _build_detail_xls,
    _assign_invoice_product_line,
    _cover_payload,
    _normalize_vehicle_rows,
    _period_parts,
    _seed_product_lines,
    _sort_rows_by_date,
    _summary,
    _sync_invoice_aux,
    register_routes,
)


def _style_signature(book, sheet, row, col):
    xf = book.xf_list[sheet.cell_xf_index(row, col)]
    font = dict(book.font_list[xf.font_index].__dict__)
    font.pop("font_index", None)
    return (
        font,
        book.format_map[xf.format_key].format_str,
        xf.alignment.__dict__,
        {
            key: value
            for key, value in xf.border.__dict__.items()
            if not (key.endswith("colour_index") and value == 0)
        },
        xf.background.__dict__,
    )


def _formula_cells(contents):
    """Return (sheet_index, row, col) locations from BIFF FORMULA records."""
    stream = CompDoc(contents).get_named_stream("Workbook")
    position = 0
    sheet_index = -1
    cells = set()
    while position + 4 <= len(stream):
        record_id, size = struct.unpack_from("<HH", stream, position)
        payload = stream[position + 4 : position + 4 + size]
        if record_id == 0x0809 and size >= 4:
            substream_type = struct.unpack_from("<H", payload, 2)[0]
            if substream_type == 0x0010:
                sheet_index += 1
        elif record_id == 0x0006 and size >= 6 and sheet_index >= 0:
            row, col = struct.unpack_from("<HH", payload, 0)
            cells.add((sheet_index, row, col))
        position += 4 + size
    return cells


class ReimbursementManagerTests(unittest.TestCase):
    def setUp(self):
        keys = [key for _, key, _ in DEFAULT_CATEGORIES]
        self.cover_data = {
            "header": {
                "employee_name": "测试员工",
                "department": "业务部",
                "office": "深圳办",
                "date": "2026-07-29",
                "period": "2026年7-8月",
            },
            "groups": [
                {
                    "product_line": "DIODES",
                    "code": "01",
                    "office": "深圳办",
                    "totals": {**{key: 0 for key in keys}, "entertainment": 100.5},
                    "remarks": ["测试"],
                }
            ],
            "grand_totals": {**{key: 0 for key in keys}, "entertainment": 100.5},
            "level_groups": [
                {
                    "level": "A",
                    "entertainment": 100.5,
                    "travel": 0,
                    "other": 0,
                    "total": 100.5,
                }
            ],
            "total_all": 100.5,
            "total_cn": "壹佰元伍角",
        }

    def test_vehicle_odometer_rows_use_entered_km_and_chain_start_end(self):
        rows = _normalize_vehicle_rows(
            [
                {"km_start": "100", "km_end": "999", "km_total": "12.5"},
                {"km_start": "888", "km_end": "999", "km_total": "7.25"},
                {"km_start": "777", "km_end": "999", "km_total": "3"},
            ]
        )

        self.assertEqual(rows[0]["km_start"], 100.0)
        self.assertEqual(rows[0]["km_end"], 112.5)
        self.assertEqual(rows[1]["km_start"], 112.5)
        self.assertEqual(rows[1]["km_end"], 119.75)
        self.assertEqual(rows[2]["km_start"], 119.75)
        self.assertEqual(rows[2]["km_end"], 122.75)
        self.assertEqual([row["km_total"] for row in rows], ["12.5", "7.25", "3"])

    def test_vehicle_odometer_rows_convert_legacy_start_end_to_km(self):
        rows = _normalize_vehicle_rows(
            [
                {"km_start": 100, "km_end": 110},
                {"km_start": 200, "km_end": 220},
            ],
            legacy_km_from_end=True,
        )

        self.assertEqual(rows[0]["km_total"], 10.0)
        self.assertEqual(rows[1]["km_total"], 20.0)
        self.assertEqual(rows[1]["km_start"], 110.0)
        self.assertEqual(rows[1]["km_end"], 130.0)

    def test_detail_rows_sort_by_date_stably_with_missing_dates_last(self):
        rows = [
            {"date": "", "label": "missing"},
            {"date": "2026-07-03", "label": "later"},
            {"date": "2026-07-01", "label": "earlier-first"},
            {"date": "2026-07-01", "label": "earlier-second"},
            {"date": "not-a-date", "label": "invalid"},
        ]

        sorted_rows = _sort_rows_by_date(rows)

        self.assertEqual(
            [row["label"] for row in sorted_rows],
            ["earlier-first", "earlier-second", "later", "missing", "invalid"],
        )

    def assert_template_layout_preserved(
        self, template, output, style_cells, *, preserve_dimensions=True
    ):
        source = xlrd.open_workbook(str(template), formatting_info=True)
        generated = xlrd.open_workbook(file_contents=output.getvalue(), formatting_info=True)
        self.assertEqual(source.sheet_names(), generated.sheet_names())
        for index in range(source.nsheets):
            left, right = source.sheet_by_index(index), generated.sheet_by_index(index)
            if preserve_dimensions:
                self.assertEqual((left.nrows, left.ncols), (right.nrows, right.ncols))
            self.assertEqual(set(left.merged_cells), set(right.merged_cells))
            self.assertEqual(left.vertical_page_breaks, right.vertical_page_breaks)
            self.assertEqual(left.horizontal_page_breaks, right.horizontal_page_breaks)
            for row in range(min(left.nrows, right.nrows)):
                left_info, right_info = left.rowinfo_map.get(row), right.rowinfo_map.get(row)
                self.assertEqual(left_info.height if left_info else None, right_info.height if right_info else None)
            for col in range(min(left.ncols, right.ncols)):
                left_info, right_info = left.colinfo_map.get(col), right.colinfo_map.get(col)
                self.assertEqual(left_info.width if left_info else None, right_info.width if right_info else None)
        for sheet_index, row, col in style_cells:
            left, right = source.sheet_by_index(sheet_index), generated.sheet_by_index(sheet_index)
            self.assertEqual(
                _style_signature(source, left, row, col),
                _style_signature(generated, right, row, col),
            )
        return generated

    def test_period_inference_handles_cross_year(self):
        self.assertEqual(_period_parts("2025年12月-2026年1月"), (2025, 12, 2026, 1))
        self.assertEqual(_period_parts("2026年7-8月"), (2026, 7, 2026, 8))

    def test_period_switch_keeps_each_period_data_isolated(self):
        app = Flask(__name__)
        app.config.update(
            SECRET_KEY="test",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(app)
        login_manager.init_app(app)
        login_manager.user_loader(lambda _user_id: None)
        blueprint = Blueprint(
            "rb_period_isolation_test",
            __name__,
            url_prefix="/tools/reimbursement",
        )
        register_routes(blueprint)
        app.register_blueprint(blueprint)
        with app.app_context():
            db.create_all()
        client = app.test_client()
        headers = {"X-RB-Anon-Id": "period-isolation-test"}
        bootstrap = client.get(
            "/tools/reimbursement/api/bootstrap", headers=headers
        ).get_json()
        office_id = bootstrap["offices"][0]["id"]

        july_august = client.post(
            "/tools/reimbursement/api/periods",
            headers=headers,
            json={
                "name": "2026年7-8月",
                "employee_name": "七八月报销人",
                "start_year": 2026,
                "start_month": 7,
                "end_year": 2026,
                "end_month": 8,
            },
        ).get_json()["period"]
        old_invoice = client.post(
            "/tools/reimbursement/api/invoices",
            headers=headers,
            json={
                "period_id": july_august["id"],
                "office_id": office_id,
                "invoice_number": "JUL-AUG-ONLY",
                "total_amount": 128,
            },
        )
        self.assertEqual(old_invoice.status_code, 201)
        saved_aux = client.put(
            f"/tools/reimbursement/api/aux/{july_august['id']}",
            headers=headers,
            json={
                "entertainment": [
                    {"date": "2026-07-15", "amount": 128, "purpose": "DIODES"}
                ],
                "vehicle": [],
                "travel": [],
            },
        )
        self.assertEqual(saved_aux.status_code, 200)

        august_september = client.post(
            "/tools/reimbursement/api/periods",
            headers=headers,
            json={
                "name": "2026年8-9月",
                "start_year": 2026,
                "start_month": 8,
                "end_year": 2026,
                "end_month": 9,
            },
        )
        self.assertEqual(august_september.status_code, 201)
        august_september = august_september.get_json()["period"]
        self.assertTrue(august_september["is_active"])

        new_bootstrap = client.get(
            "/tools/reimbursement/api/bootstrap", headers=headers
        ).get_json()
        self.assertEqual(new_bootstrap["stats"]["period_id"], august_september["id"])
        self.assertEqual(new_bootstrap["stats"]["invoice_count"], 0)
        self.assertEqual(new_bootstrap["recent"], [])
        new_summary = client.get(
            f"/tools/reimbursement/api/summary/{august_september['id']}",
            headers=headers,
        ).get_json()
        self.assertEqual(new_summary["summary"]["invoice_count"], 0)
        self.assertEqual(
            new_summary["aux"],
            {"entertainment": [], "vehicle": [], "travel": []},
        )

        old_summary = client.get(
            f"/tools/reimbursement/api/summary/{july_august['id']}",
            headers=headers,
        ).get_json()
        self.assertEqual(old_summary["summary"]["invoice_count"], 1)
        self.assertEqual(len(old_summary["aux"]["entertainment"]), 1)
        activated = client.post(
            f"/tools/reimbursement/api/periods/{july_august['id']}/activate",
            headers=headers,
            json={},
        )
        self.assertEqual(activated.status_code, 200)
        old_bootstrap = client.get(
            "/tools/reimbursement/api/bootstrap", headers=headers
        ).get_json()
        self.assertEqual(old_bootstrap["stats"]["period_id"], july_august["id"])
        self.assertEqual(old_bootstrap["stats"]["invoice_count"], 1)
        self.assertEqual(old_bootstrap["recent"][0]["invoice_number"], "JUL-AUG-ONLY")

        next_period = client.post(
            "/tools/reimbursement/api/periods/next",
            headers=headers,
            json={},
        )
        self.assertEqual(next_period.status_code, 201)
        self.assertEqual(next_period.get_json()["period"]["employee_name"], "")
        self.assertTrue(next_period.get_json()["period"]["is_active"])

    def test_invoice_creates_and_updates_linked_detail(self):
        app = Flask(__name__)
        app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(app)
        with app.app_context():
            db.create_all()
            period = ReimbursementPeriod(
                owner_type="anon",
                owner_id="test",
                name="2026年7-8月",
                start_year=2026,
                start_month=7,
                end_year=2026,
                end_month=8,
            )
            entertainment = ReimbursementCategory(
                owner_type="anon", owner_id="test", name="招待费", export_key="entertainment"
            )
            travel = ReimbursementCategory(
                owner_type="anon", owner_id="test", name="出差住宿费", export_key="travel_hotel"
            )
            db.session.add_all([period, entertainment, travel])
            db.session.flush()
            invoice = ReimbursementInvoice(
                owner_type="anon",
                owner_id="test",
                period_id=period.id,
                category_id=entertainment.id,
                invoice_number="INV-1",
                invoice_date=date(2026, 7, 1),
                total_amount=100.5,
                vendor="测试餐厅",
                product_line="DIODES",
            )
            db.session.add(invoice)
            db.session.flush()
            _sync_invoice_aux(invoice, entertainment, {"customer": "客户A", "participants": "张三"})
            db.session.flush()
            row = ReimbursementAuxDetail.query.one()
            self.assertEqual(row.kind, "entertainment")
            self.assertEqual(json.loads(row.data_json)["invoice_id"], invoice.id)

            invoice.category_id = travel.id
            _sync_invoice_aux(invoice, travel, {"location": "上海", "customer": "客户B"})
            db.session.flush()
            rows = ReimbursementAuxDetail.query.all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].kind, "travel")
            self.assertEqual(json.loads(rows[0].data_json)["location"], "上海")

    def test_product_lines_seed_from_workbook_and_code_is_server_matched(self):
        app = Flask(__name__)
        app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(app)
        with app.app_context():
            db.create_all()
            rows = _seed_product_lines("anon", "product-test")
            self.assertEqual(len(rows), len(PRODUCT_LINES))
            diodes = ReimbursementProductLine.query.filter_by(
                owner_type="anon", owner_id="product-test", name="DIODES"
            ).one()
            self.assertEqual(diodes.code, "10")
            invoice = ReimbursementInvoice(
                owner_type="anon",
                owner_id="product-test",
                period_id=1,
                product_line="",
                product_line_code="",
            )
            error = _assign_invoice_product_line(
                invoice,
                {
                    "product_line_id": diodes.id,
                    "product_line": "错误名称",
                    "product_line_code": "9999",
                },
            )
            self.assertIsNone(error)
            self.assertEqual((invoice.product_line, invoice.product_line_code), ("DIODES", "10"))
            self.assertEqual(
                _assign_invoice_product_line(invoice, {"product_line_id": 999999}),
                "请选择有效的产品线",
            )

    def test_product_lines_replace_legacy_directory_once(self):
        app = Flask(__name__)
        app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(app)
        with app.app_context():
            db.create_all()
            db.session.add(
                ReimbursementProductLine(
                    owner_type="anon",
                    owner_id="legacy-product-test",
                    name="DIODES",
                    code="01",
                    office="深圳办",
                    sort_order=10,
                )
            )
            db.session.commit()

            rows = _seed_product_lines("anon", "legacy-product-test")
            self.assertEqual(
                [(item.code, item.name) for item in rows],
                [(item["code"], item["name"]) for item in PRODUCT_LINES],
            )
            self.assertEqual(rows[0].code, "01")
            self.assertEqual(rows[0].name, "3PEAK")
            self.assertEqual(rows[-1].code, "86")
            self.assertEqual(rows[-1].name, "致象尔微")

            rows[0].name = "自定义品牌"
            db.session.commit()
            rows_again = _seed_product_lines("anon", "legacy-product-test")
            self.assertEqual(rows_again[0].name, "自定义品牌")

    def test_product_line_crud_updates_and_migrates_linked_invoices(self):
        app = Flask(__name__)
        app.config.update(
            SECRET_KEY="test",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(app)
        login_manager.init_app(app)
        login_manager.user_loader(lambda _user_id: None)
        blueprint = Blueprint("rb_product_test", __name__, url_prefix="/tools/reimbursement")
        register_routes(blueprint)
        app.register_blueprint(blueprint)
        with app.app_context():
            db.create_all()
        client = app.test_client()
        headers = {"X-RB-Anon-Id": "crud-test"}
        bootstrap = client.get("/tools/reimbursement/api/bootstrap", headers=headers).get_json()
        by_name = {item["name"]: item for item in bootstrap["product_lines"]}
        office = bootstrap["offices"][0]
        period = client.post(
            "/tools/reimbursement/api/periods",
            headers=headers,
            json={
                "name": "2026年7-8月",
                "start_year": 2026,
                "start_month": 7,
                "end_year": 2026,
                "end_month": 8,
            },
        ).get_json()["period"]
        invoice_response = client.post(
            "/tools/reimbursement/api/invoices",
            headers=headers,
            json={
                "period_id": period["id"],
                "product_line_id": by_name["DIODES"]["id"],
                "product_line_code": "错误代码",
                "office_id": office["id"],
                "invoice_number": "PL-1",
                "total_amount": 88,
            },
        )
        self.assertEqual(invoice_response.status_code, 201)
        self.assertEqual(invoice_response.get_json()["invoice"]["product_line_code"], "10")

        updated = client.put(
            f"/tools/reimbursement/api/product-lines/{by_name['DIODES']['id']}",
            headers=headers,
            json={"name": "DIODES-NEW", "code": "0100", "office": "深圳办"},
        )
        self.assertEqual(updated.status_code, 200)
        invoices = client.get("/tools/reimbursement/api/invoices", headers=headers).get_json()["invoices"]
        self.assertEqual((invoices[0]["product_line"], invoices[0]["product_line_code"]), ("DIODES-NEW", "0100"))

        blocked = client.delete(
            f"/tools/reimbursement/api/product-lines/{by_name['DIODES']['id']}",
            headers=headers,
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertTrue(blocked.get_json()["needs_migration"])
        migrated = client.delete(
            f"/tools/reimbursement/api/product-lines/{by_name['DIODES']['id']}?migrate_to={by_name['3PEAK']['id']}",
            headers=headers,
        )
        self.assertEqual(migrated.status_code, 200)
        invoices = client.get("/tools/reimbursement/api/invoices", headers=headers).get_json()["invoices"]
        self.assertEqual((invoices[0]["product_line"], invoices[0]["product_line_code"]), ("3PEAK", "01"))

    def test_office_crud_is_independent_and_prints_retained_invoice(self):
        app = Flask(__name__)
        with tempfile.TemporaryDirectory() as upload_root:
            app.config.update(
                SECRET_KEY="test",
                SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                SQLALCHEMY_TRACK_MODIFICATIONS=False,
                UPLOAD_DIR=upload_root,
            )
            db.init_app(app)
            login_manager.init_app(app)
            login_manager.user_loader(lambda _user_id: None)
            blueprint = Blueprint("rb_office_test", __name__, url_prefix="/tools/reimbursement")
            register_routes(blueprint)
            app.register_blueprint(blueprint)
            with app.app_context():
                db.create_all()
            client = app.test_client()
            headers = {"X-RB-Anon-Id": "office-test"}
            bootstrap = client.get("/tools/reimbursement/api/bootstrap", headers=headers).get_json()
            self.assertEqual([item["name"] for item in bootstrap["offices"]], DEFAULT_OFFICES)
            self.assertNotIn("office", bootstrap["product_lines"][0])

            created = client.post(
                "/tools/reimbursement/api/offices",
                headers=headers,
                json={"name": "测试办", "sort_order": 5},
            )
            self.assertEqual(created.status_code, 201)
            test_office = created.get_json()["office"]
            period = client.post(
                "/tools/reimbursement/api/periods",
                headers=headers,
                json={
                    "name": "2026年9-10月",
                    "employee_name": "张三",
                    "start_year": 2026,
                    "start_month": 9,
                    "end_year": 2026,
                    "end_month": 10,
                },
            ).get_json()["period"]

            upload_dir = Path(upload_root) / "reimbursement"
            upload_dir.mkdir(parents=True)
            file_id = "abc123def456"
            (upload_dir / f"{file_id}.png").write_bytes(
                __import__("base64").b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n1cAAAAASUVORK5CYII="
                )
            )
            invoice = client.post(
                "/tools/reimbursement/api/invoices",
                headers=headers,
                json={
                    "period_id": period["id"],
                    "office_id": test_office["id"],
                    "invoice_number": "PRINT-1",
                    "file_name": "发票.png",
                    "file_url": f"/tools/reimbursement/preview/{file_id}.png",
                },
            )
            self.assertEqual(invoice.status_code, 201)
            self.assertEqual(invoice.get_json()["invoice"]["office"], "测试办")

            renamed = client.put(
                f"/tools/reimbursement/api/periods/{period['id']}",
                headers=headers,
                json={"employee_name": "李四"},
            )
            self.assertEqual(renamed.status_code, 200)
            summary = client.get(
                f"/tools/reimbursement/api/summary/{period['id']}",
                headers=headers,
            ).get_json()["summary"]
            self.assertEqual(summary["period"]["employee_name"], "李四")

            cover_export = client.get(
                f"/tools/reimbursement/api/export/cover/{period['id']}",
                headers=headers,
            )
            detail_export = client.get(
                f"/tools/reimbursement/api/export/details/{period['id']}",
                headers=headers,
            )
            self.assertEqual((cover_export.status_code, detail_export.status_code), (200, 200))
            cover_book = xlrd.open_workbook(file_contents=cover_export.data)
            detail_book = xlrd.open_workbook(file_contents=detail_export.data)
            self.assertEqual(cover_book.sheet_by_name("封面").cell_value(3, 2), "李四")
            self.assertIn("李四", detail_book.sheet_by_name("应酬费明细表").cell_value(1, 0))

            updated = client.put(
                f"/tools/reimbursement/api/offices/{test_office['id']}",
                headers=headers,
                json={"name": "测试办-新", "sort_order": 6},
            )
            self.assertEqual(updated.status_code, 200)
            invoices = client.get("/tools/reimbursement/api/invoices", headers=headers).get_json()["invoices"]
            self.assertEqual(invoices[0]["office"], "测试办-新")

            printed = client.get(
                f"/tools/reimbursement/api/periods/{period['id']}/invoices/print",
                headers=headers,
            )
            self.assertEqual(printed.status_code, 200)
            print_html = printed.get_data(as_text=True)
            self.assertIn("window.print()", print_html)
            self.assertNotIn("<header>", print_html)
            self.assertNotIn("PRINT-1", print_html)
            self.assertIn('alt="发票原件"', print_html)
            self.assertIn(
                "@page{size:A5 landscape;margin:6mm}",
                print_html,
            )
            self.assertIn(
                "width:198mm;height:136mm;min-height:136mm",
                print_html,
            )

            blocked = client.delete(
                f"/tools/reimbursement/api/offices/{test_office['id']}",
                headers=headers,
            )
            self.assertEqual(blocked.status_code, 409)
            target = bootstrap["offices"][0]
            migrated = client.delete(
                f"/tools/reimbursement/api/offices/{test_office['id']}?migrate_to={target['id']}",
                headers=headers,
            )
            self.assertEqual(migrated.status_code, 200)

    def test_cover_export_uses_original_workbook_layout(self):
        output = _build_cover_xls(self.cover_data)
        generated = self.assert_template_layout_preserved(
            COVER_TEMPLATE,
            output,
            [(0, 0, 0), (1, 0, 0), (1, 3, 2), (1, 5, 0), (1, 6, 0), (2, 0, 0)],
        )
        cover = generated.sheet_by_name("封面")
        self.assertEqual(cover.cell_value(3, 2), "测试员工")
        self.assertEqual(cover.cell_value(6, 1), "DIODES")
        self.assertEqual(cover.cell_value(6, 5), 100.5)
        self.assertEqual(cover.cell_value(20, 7), 100.5)

    def test_entertainment_categories_include_gift(self):
        self.assertIn("餐费", ENTERTAINMENT_CATEGORIES)
        self.assertIn("礼品", ENTERTAINMENT_CATEGORIES)

    def test_summary_vehicle_row_includes_dispatch_fees_and_replaces_covered_invoices(self):
        app = Flask(__name__)
        app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(app)
        with app.app_context():
            db.create_all()
            period = ReimbursementPeriod(
                owner_type="anon",
                owner_id="summary-vehicle",
                name="2026年7-8月",
                start_year=2026,
                start_month=7,
                end_year=2026,
                end_month=8,
                office="深圳办",
            )
            vehicle = ReimbursementCategory(
                owner_type="anon",
                owner_id="summary-vehicle",
                name="车辆费用",
                export_key="vehicle",
            )
            other = ReimbursementCategory(
                owner_type="anon",
                owner_id="summary-vehicle",
                name="其他",
                export_key="other",
            )
            db.session.add_all([period, vehicle, other])
            db.session.flush()
            db.session.add(
                ReimbursementInvoice(
                    owner_type="anon",
                    owner_id="summary-vehicle",
                    period_id=period.id,
                    category_id=vehicle.id,
                    total_amount=999,
                    product_line="DIODES",
                    product_line_code="01",
                )
            )
            db.session.add(
                ReimbursementInvoice(
                    owner_type="anon",
                    owner_id="summary-vehicle",
                    period_id=period.id,
                    category_id=vehicle.id,
                    total_amount=40,
                    product_line="MSTAR",
                    product_line_code="02",
                )
            )
            db.session.add(
                ReimbursementAuxDetail(
                    owner_type="anon",
                    owner_id="summary-vehicle",
                    period_id=period.id,
                    kind="vehicle",
                    sort_order=0,
                    data_json=json.dumps(
                        {
                            "km_start": 100,
                            "km_end": 135.5,
                            "toll_fee": 10,
                            "parking_fee": 5,
                            "product_line": "DIODES",
                        }
                    ),
                )
            )
            db.session.add(
                ReimbursementAuxDetail(
                    owner_type="anon",
                    owner_id="summary-vehicle",
                    period_id=period.id,
                    kind="vehicle",
                    sort_order=1,
                    data_json=json.dumps(
                        {
                            "km_start": 200,
                            "km_end": 220,
                            "toll_fee": 2,
                            "parking_fee": 3,
                            "product_line": "DIODES",
                        }
                    ),
                )
            )
            db.session.commit()

            summary = _summary(period)
            vehicle_row = next(
                item
                for item in summary["by_category"]
                if item["export_key"] == "vehicle"
            )
            # DIODES 派车单：35.5 + 10 + 5 + 20 + 2 + 3 = 75.5，替代同产品线发票 999；
            # MSTAR 无派车单，保留车辆类发票 40。
            self.assertEqual(vehicle_row["invoice_count"], 2)
            self.assertEqual(vehicle_row["total_amount"], 115.5)
            self.assertEqual(vehicle_row["amount"], 115.5)
            self.assertEqual(vehicle_row["tax_amount"], 0)
            self.assertEqual(summary["total_amount"], 115.5)

    def test_vehicle_details_replace_invoice_vehicle_fee_and_group_by_product_line(self):
        app = Flask(__name__)
        app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(app)
        with app.app_context():
            db.create_all()
            period = ReimbursementPeriod(
                owner_type="anon",
                owner_id="vehicle-cover",
                name="2026年7-8月",
                start_year=2026,
                start_month=7,
                end_year=2026,
                end_month=8,
                office="深圳办",
            )
            category = ReimbursementCategory(
                owner_type="anon",
                owner_id="vehicle-cover",
                name="车辆费用",
                export_key="vehicle",
            )
            product_line = ReimbursementProductLine(
                owner_type="anon",
                owner_id="vehicle-cover",
                name="3PEAK",
                code="01",
            )
            second_product_line = ReimbursementProductLine(
                owner_type="anon",
                owner_id="vehicle-cover",
                name="Adaps",
                code="02",
            )
            db.session.add_all(
                [period, category, product_line, second_product_line]
            )
            db.session.flush()
            db.session.add(
                ReimbursementInvoice(
                    owner_type="anon",
                    owner_id="vehicle-cover",
                    period_id=period.id,
                    category_id=category.id,
                    total_amount=999,
                    product_line="3PEAK",
                    product_line_code="01",
                    office="深圳办",
                )
            )
            db.session.add(
                ReimbursementAuxDetail(
                    owner_type="anon",
                    owner_id="vehicle-cover",
                    period_id=period.id,
                    kind="vehicle",
                    sort_order=0,
                    data_json=json.dumps(
                        {
                            "km_start": 100,
                            "km_end": 135.5,
                            "toll_fee": 10,
                            "parking_fee": 5,
                            "product_line": "3PEAK",
                        }
                    ),
                )
            )
            db.session.add(
                ReimbursementAuxDetail(
                    owner_type="anon",
                    owner_id="vehicle-cover",
                    period_id=period.id,
                    kind="vehicle",
                    sort_order=1,
                    data_json=json.dumps(
                        {
                            "km_start": 200,
                            "km_end": 220,
                            "toll_fee": 2,
                            "parking_fee": 3,
                            "product_line": "3PEAK",
                        }
                    ),
                )
            )
            db.session.add(
                ReimbursementAuxDetail(
                    owner_type="anon",
                    owner_id="vehicle-cover",
                    period_id=period.id,
                    kind="vehicle",
                    sort_order=2,
                    data_json=json.dumps(
                        {
                            "km_start": 300,
                            "km_end": 310,
                            "toll_fee": 1,
                            "parking_fee": 1,
                            "product_line": "Adaps",
                        }
                    ),
                )
            )
            db.session.commit()

            payload = _cover_payload(period)
            group = next(
                item for item in payload["groups"] if item["product_line"] == "3PEAK"
            )
            second_group = next(
                item for item in payload["groups"] if item["product_line"] == "Adaps"
            )
            self.assertEqual(group["totals"]["vehicle"], 75.5)
            self.assertEqual(second_group["totals"]["vehicle"], 12)
            self.assertEqual(payload["grand_totals"]["vehicle"], 87.5)
            self.assertEqual(payload["total_all"], 87.5)
            cover = xlrd.open_workbook(
                file_contents=_build_cover_xls(payload).getvalue()
            ).sheet_by_name("封面")
            self.assertEqual(cover.cell_value(6, 9), 75.5)
            self.assertEqual(cover.cell_value(7, 9), 12)
            self.assertEqual(cover.cell_value(18, 9), 87.5)

    def test_detail_export_uses_original_workbook_layout(self):
        output = _build_detail_xls(
            self.cover_data,
            {
                "entertainment": [
                    {
                        "date": "2026-06-30",
                        "category": "礼品",
                        "place": "更早地点",
                        "customer": "客户B",
                        "participants": "李四",
                        "amount": 50,
                        "purpose": "MSTAR",
                    },
                    {
                        "date": "2026-07-01",
                        "category": "餐费",
                        "place": "测试餐厅",
                        "customer": "客户",
                        "participants": "张三",
                        "amount": 100.5,
                        "purpose": "DIODES",
                    }
                ],
                "vehicle": [
                    {
                        "date": "2026-07-02",
                        "from_location": "公司",
                        "to_location": "客户",
                        "km_start": 100,
                        "km_end": 135.5,
                        "toll_fee": 10,
                        "parking_fee": 5,
                        "product_line": "DIODES",
                    },
                    {
                        "date": "2026-07-01",
                        "from_location": "家",
                        "to_location": "公司",
                        "km_start": 90,
                        "km_total": 10,
                        "toll_fee": 0,
                        "parking_fee": 0,
                        "product_line": "MSTAR",
                    }
                ],
                "travel": [
                    {
                        "date": "2026-07-03",
                        "location": "上海",
                        "customer": "客户",
                        "expense_type": "住宿费",
                        "amount": 300,
                        "purpose": "DIODES",
                    },
                    {
                        "date": "2026-07-01",
                        "location": "杭州",
                        "customer": "客户B",
                        "expense_type": "交通费",
                        "amount": 80,
                        "purpose": "MSTAR",
                    }
                ],
            },
        )
        generated = self.assert_template_layout_preserved(
            DETAIL_TEMPLATE,
            output,
            [(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 3, 0), (0, 3, 5), (1, 0, 0), (2, 0, 0)],
            preserve_dimensions=False,
        )
        self.assertEqual(
            [(sheet.nrows, sheet.ncols) for sheet in generated.sheets()],
            [(13, 8), (16, 10), (21, 6)],
        )
        detail = generated.sheet_by_name("应酬费明细表")
        self.assertEqual(detail.cell_value(1, 0), "员工姓名：测试员工")
        self.assertEqual(detail.cell_value(3, 2), "更早地点")
        self.assertEqual(detail.cell_value(3, 5), 50)
        self.assertEqual(detail.cell_value(4, 2), "测试餐厅")
        self.assertEqual(detail.cell_value(12, 0), "合计")
        vehicle = generated.sheet_by_name("派车单")
        self.assertEqual(vehicle.cell_value(2, 9), "产品线")
        self.assertEqual(vehicle.cell_value(4, 9), "MSTAR")
        self.assertEqual(vehicle.cell_value(5, 9), "DIODES")
        travel = generated.sheet_by_name("出差明细表")
        self.assertEqual(travel.cell_value(3, 1), "杭州")
        self.assertEqual(travel.cell_value(4, 1), "上海")
        self.assertEqual(travel.cell_value(20, 0), "合计")
        formulas = _formula_cells(output.getvalue())
        self.assertTrue(
            {
                (0, 12, 5),
                (1, 4, 5),
                (1, 15, 6),
                (1, 15, 7),
                (1, 15, 8),
                (2, 20, 4),
            }.issubset(formulas)
        )

    def test_detail_export_expands_past_template_row_limits(self):
        entertainment = [
            {
                "date": f"2026-07-{index + 1:02d}",
                "category": "餐费",
                "place": f"应酬地点{index}",
                "amount": index + 1,
            }
            for index in range(12)
        ]
        vehicles = [
            {
                "date": "2026-07-01",
                "from_location": "公司",
                "to_location": f"目的地{index}",
                "km_start": 100 if index == 0 else "",
                "km_total": index + 1,
                "toll_fee": 1,
                "parking_fee": 2,
                "product_line": f"产品线{index}",
            }
            for index in range(14)
        ]
        travels = [
            {
                "date": f"2026-07-{index + 1:02d}",
                "location": f"出差地{index}",
                "amount": index + 1,
            }
            for index in range(20)
        ]

        output = _build_detail_xls(
            self.cover_data,
            {
                "entertainment": entertainment,
                "vehicle": vehicles,
                "travel": travels,
            },
        )
        generated = xlrd.open_workbook(
            file_contents=output.getvalue(), formatting_info=True
        )
        baseline = xlrd.open_workbook(
            file_contents=_build_detail_xls(
                self.cover_data,
                {"entertainment": [], "vehicle": [], "travel": []},
            ).getvalue(),
            formatting_info=True,
        )
        self.assertEqual(
            [(sheet.nrows, sheet.ncols) for sheet in generated.sheets()],
            [(16, 8), (19, 10), (24, 6)],
        )

        detail = generated.sheet_by_name("应酬费明细表")
        baseline_detail = baseline.sheet_by_name("应酬费明细表")
        self.assertEqual(detail.cell_value(14, 2), "应酬地点11")
        self.assertEqual(detail.cell_value(15, 0), "合计")
        self.assertEqual(
            _style_signature(generated, detail, 14, 2),
            _style_signature(baseline, baseline_detail, 3, 2),
        )
        self.assertEqual(
            _style_signature(generated, detail, 15, 5),
            _style_signature(baseline, baseline_detail, 12, 5),
        )
        self.assertEqual(detail.rowinfo_map[14].height, baseline_detail.rowinfo_map[3].height)

        vehicle = generated.sheet_by_name("派车单")
        baseline_vehicle = baseline.sheet_by_name("派车单")
        self.assertEqual(vehicle.cell_value(17, 9), "产品线13")
        self.assertEqual(vehicle.cell_value(18, 0), "合计")
        self.assertEqual(
            _style_signature(generated, vehicle, 17, 9),
            _style_signature(baseline, baseline_vehicle, 4, 9),
        )
        self.assertEqual(
            _style_signature(generated, vehicle, 18, 6),
            _style_signature(baseline, baseline_vehicle, 15, 6),
        )
        self.assertEqual(vehicle.rowinfo_map[17].height, baseline_vehicle.rowinfo_map[4].height)

        travel = generated.sheet_by_name("出差明细表")
        baseline_travel = baseline.sheet_by_name("出差明细表")
        self.assertEqual(travel.cell_value(22, 1), "出差地19")
        self.assertEqual(travel.cell_value(23, 0), "合计")
        self.assertEqual(
            _style_signature(generated, travel, 22, 1),
            _style_signature(baseline, baseline_travel, 3, 1),
        )
        self.assertEqual(
            _style_signature(generated, travel, 23, 4),
            _style_signature(baseline, baseline_travel, 20, 4),
        )
        self.assertEqual(travel.rowinfo_map[22].height, baseline_travel.rowinfo_map[3].height)

        formulas = _formula_cells(output.getvalue())
        self.assertTrue(
            {
                (0, 15, 5),
                (1, 17, 5),
                (1, 18, 6),
                (1, 18, 7),
                (1, 18, 8),
                (2, 23, 4),
            }.issubset(formulas)
        )

    def test_summary_export_view_has_independent_click_entry(self):
        template = (
            Path(__file__).parents[1]
            / "templates"
            / "tools"
            / "reimbursement"
            / "_body.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'data-view="export"',
            template,
        )
        self.assertIn("button=e.target.closest('button[data-view]')", template)
        self.assertIn("export:'rbViewExport'", template)
        self.assertIn("if(document.readyState==='loading')", template)
        self.assertIn("flex-wrap:nowrap", template)
        self.assertIn("scrollbar-width:none", template)
        self.assertIn("-webkit-overflow-scrolling:touch", template)
        self.assertIn("pointer-events:none", template)
        self.assertIn(".rb-nav-frame { position:relative; z-index:1;", template)
        self.assertIn('id="rbNavNext"', template)
        self.assertIn("this.state.aux=d.aux;this.renderAux()", template)
        self.assertIn("scrollNav(direction)", template)
        self.assertIn("revealNavButton(button)", template)
        self.assertIn("normalizeVehicleRows()", template)
        self.assertIn("(start+km)*100", template)
        self.assertIn("key==='km_start'&&ri>0", template)
        self.assertIn("rbViewExport').addEventListener('input'", template)
        self.assertIn("['product_line','产品线','product-line']", template)
        self.assertIn("['purpose','产品线','product-line']", template)
        self.assertIn("invoiceCategories=this.state.categories.filter", template)
        self.assertIn("['communication','welfare']", template)
        self.assertIn("if(i&&!i.category_id", template)
        self.assertIn("entertainmentCategories()", template)
        self.assertIn("categoryOptions(value)", template)
        self.assertIn("（历史数据）", template)
        self.assertIn("礼品", template)
        self.assertEqual(
            template.count("['purpose','产品线','product-line']"),
            2,
        )
        self.assertIn("请选择产品线", template)
        self.assertIn(">${this.esc(p.name)}</option>`).join('')", template)
        self.assertIn('id="rbWorkspacePeriod"', template)
        self.assertIn("进入本周期", template)
        self.assertIn("/activate',{method:'POST'", template)
        self.assertIn("新周期已创建，已进入空白周期", template)

    def test_uploaded_invoice_survives_local_file_loss(self):
        app = Flask(__name__)
        with tempfile.TemporaryDirectory() as upload_root:
            app.config.update(
                SECRET_KEY="test",
                SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                SQLALCHEMY_TRACK_MODIFICATIONS=False,
                UPLOAD_DIR=upload_root,
                ANON_FREE_LIMIT=10,
                DAILY_FREE_LIMIT=10,
                RATELIMIT_ENABLED=False,
                WTF_CSRF_ENABLED=False,
            )
            db.init_app(app)
            login_manager.init_app(app)
            login_manager.user_loader(lambda _user_id: None)
            csrf.init_app(app)
            limiter.init_app(app)
            app.register_blueprint(tool_bp, url_prefix="/tools/reimbursement")
            with app.app_context():
                db.create_all()
            client = app.test_client()
            headers = {"X-RB-Anon-Id": "attachment-test"}
            image = __import__("base64").b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n1cAAAAASUVORK5CYII="
            )
            uploaded = client.post(
                "/tools/reimbursement/upload",
                headers=headers,
                data={"file": (io.BytesIO(image), "发票.png")},
                content_type="multipart/form-data",
            )
            self.assertEqual(uploaded.status_code, 200)
            upload_data = uploaded.get_json()
            stored_name = upload_data["filename"]
            bootstrap = client.get(
                "/tools/reimbursement/api/bootstrap", headers=headers
            ).get_json()
            period = client.post(
                "/tools/reimbursement/api/periods",
                headers=headers,
                json={
                    "name": "附件持久化测试",
                    "start_year": 2026,
                    "start_month": 7,
                    "end_year": 2026,
                    "end_month": 8,
                },
            ).get_json()["period"]
            invoice = client.post(
                "/tools/reimbursement/api/invoices",
                headers=headers,
                json={
                    "period_id": period["id"],
                    "office_id": bootstrap["offices"][0]["id"],
                    "invoice_number": "PERSIST-1",
                    "file_url": upload_data["original_url"],
                    "file_name": upload_data["original_name"],
                    "file_size": upload_data["size"],
                },
            )
            self.assertEqual(invoice.status_code, 201)
            self.assertEqual(
                invoice.get_json()["invoice"]["file_url"],
                upload_data["original_url"],
            )
            with app.app_context():
                attachment = ReimbursementAttachment.query.filter_by(
                    stored_name=stored_name
                ).one()
                self.assertEqual(attachment.content, image)
            stored_path = Path(upload_root) / "reimbursement" / stored_name
            stored_path.unlink()
            preview = client.get(f"/tools/reimbursement/preview/{stored_name}")
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.data, image)


if __name__ == "__main__":
    unittest.main()
