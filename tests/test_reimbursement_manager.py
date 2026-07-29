from __future__ import annotations

import io
import unittest

import xlrd

from tools.reimbursement.manager import (
    COVER_TEMPLATE,
    DEFAULT_CATEGORIES,
    DETAIL_TEMPLATE,
    _build_cover_xls,
    _build_detail_xls,
    _period_parts,
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
                "vehicle": [],
                "travel": [],
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
        self.assertEqual(detail.cell_value(12, 5), 100.5)


if __name__ == "__main__":
    unittest.main()
