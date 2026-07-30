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
from tools.reimbursement import PRODUCT_LINES, tool_bp
from tools.reimbursement.manager import (
    COVER_TEMPLATE,
    DEFAULT_CATEGORIES,
    DEFAULT_OFFICES,
    DETAIL_TEMPLATE,
    _build_cover_xls,
    _build_detail_xls,
    _assign_invoice_product_line,
    _cover_payload,
    _period_parts,
    _seed_product_lines,
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
                    "level": "level 1",
                    "entertainment": 100.5,
                    "travel": 0,
                    "other": 0,
                    "total": 100.5,
                }
            ],
            "total_all": 100.5,
            "total_cn": "壹佰元伍角",
        }

    def assert_template_layout_preserved(self, template, output, style_cells):
        source = xlrd.open_workbook(str(template), formatting_info=True)
        generated = xlrd.open_workbook(file_contents=output.getvalue(), formatting_info=True)
        self.assertEqual(source.sheet_names(), generated.sheet_names())
        for index in range(source.nsheets):
            left, right = source.sheet_by_index(index), generated.sheet_by_index(index)
            self.assertEqual((left.nrows, left.ncols), (right.nrows, right.ncols))
            self.assertEqual(set(left.merged_cells), set(right.merged_cells))
            self.assertEqual(left.vertical_page_breaks, right.vertical_page_breaks)
            self.assertEqual(left.horizontal_page_breaks, right.horizontal_page_breaks)
            for row in range(left.nrows):
                left_info, right_info = left.rowinfo_map.get(row), right.rowinfo_map.get(row)
                self.assertEqual(left_info.height if left_info else None, right_info.height if right_info else None)
            for col in range(left.ncols):
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
            self.assertEqual(diodes.code, "01")
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
            self.assertEqual((invoice.product_line, invoice.product_line_code), ("DIODES", "01"))
            self.assertEqual(
                _assign_invoice_product_line(invoice, {"product_line_id": 999999}),
                "请选择有效的产品线",
            )

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
        self.assertEqual(invoice_response.get_json()["invoice"]["product_line_code"], "01")

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
            f"/tools/reimbursement/api/product-lines/{by_name['DIODES']['id']}?migrate_to={by_name['MSTAR']['id']}",
            headers=headers,
        )
        self.assertEqual(migrated.status_code, 200)
        invoices = client.get("/tools/reimbursement/api/invoices", headers=headers).get_json()["invoices"]
        self.assertEqual((invoices[0]["product_line"], invoices[0]["product_line_code"]), ("MSTAR", "02"))

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
            self.assertIn("window.print()", printed.get_data(as_text=True))
            self.assertIn("PRINT-1", printed.get_data(as_text=True))
            self.assertIn(
                "@page{size:A5 landscape;margin:6mm}",
                printed.get_data(as_text=True),
            )
            self.assertIn(
                "width:198mm;height:136mm;min-height:136mm",
                printed.get_data(as_text=True),
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
                name="DIODES",
                code="01",
            )
            second_product_line = ReimbursementProductLine(
                owner_type="anon",
                owner_id="vehicle-cover",
                name="MSTAR",
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
                    product_line="DIODES",
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
                            "product_line": "DIODES",
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
                            "product_line": "DIODES",
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
                            "product_line": "MSTAR",
                        }
                    ),
                )
            )
            db.session.commit()

            payload = _cover_payload(period)
            group = next(
                item for item in payload["groups"] if item["product_line"] == "DIODES"
            )
            second_group = next(
                item for item in payload["groups"] if item["product_line"] == "MSTAR"
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
                    }
                ],
            },
        )
        generated = self.assert_template_layout_preserved(
            DETAIL_TEMPLATE,
            output,
            [(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 3, 0), (0, 3, 5), (1, 0, 0), (2, 0, 0)],
        )
        detail = generated.sheet_by_name("应酬费明细表")
        self.assertEqual(detail.cell_value(1, 0), "员工姓名：测试员工")
        self.assertEqual(detail.cell_value(3, 2), "测试餐厅")
        self.assertEqual(detail.cell_value(3, 5), 100.5)
        self.assertEqual(detail.cell_value(12, 0), "合计")
        vehicle = generated.sheet_by_name("派车单")
        self.assertEqual(vehicle.cell_value(2, 9), "产品线")
        self.assertEqual(vehicle.cell_value(4, 9), "DIODES")
        self.assertEqual(generated.sheet_by_name("出差明细表").cell_value(20, 0), "合计")
        formulas = _formula_cells(output.getvalue())
        self.assertTrue(
            {
                (0, 12, 5),
                (1, 4, 6),
                (1, 15, 6),
                (1, 15, 7),
                (1, 15, 8),
                (2, 20, 4),
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
        self.assertIn("scrollNav(direction)", template)
        self.assertIn("revealNavButton(button)", template)
        self.assertIn("?(end-start).toFixed(2):''", template)
        self.assertIn("rbViewExport').addEventListener('input'", template)
        self.assertIn("['product_line','产品线','product-line']", template)
        self.assertIn("['purpose','产品线','product-line']", template)
        self.assertEqual(
            template.count("['purpose','产品线','product-line']"),
            2,
        )
        self.assertIn("请选择产品线", template)
        self.assertIn(">${this.esc(p.name)}</option>`).join('')", template)

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
