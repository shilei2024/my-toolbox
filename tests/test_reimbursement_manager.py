from __future__ import annotations

import io
import json
import struct
import unittest
from datetime import date

import xlrd
from flask import Flask
from xlrd.compdoc import CompDoc

from extensions import db
from models import ReimbursementAuxDetail, ReimbursementCategory, ReimbursementInvoice, ReimbursementPeriod
from tools.reimbursement.manager import (
    COVER_TEMPLATE,
    DEFAULT_CATEGORIES,
    DETAIL_TEMPLATE,
    _build_cover_xls,
    _build_detail_xls,
    _period_parts,
    _sync_invoice_aux,
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


if __name__ == "__main__":
    unittest.main()
