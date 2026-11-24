"""Excel export builders used by the desktop bridge.

The openpyxl import stays inside the builder: CLI/local runs must not pay for it
unless the user actually exports a workbook.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Mapping, Sequence


def _parse_amount(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.\-]", "", text)
    if not cleaned:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _append_text_row(sheet: Any, values: Sequence[Any], text_columns: set[int]) -> None:
    clean = [
        re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "\ufffd", str(value or ""))
        if index in text_columns
        else value
        for index, value in enumerate(values)
    ]
    sheet.append(clean)
    for index in text_columns:
        sheet.cell(sheet.max_row, index + 1).data_type = "s"


def write_result_detail_workbook(
    target_dir: str,
    processed_invoices: Sequence[Mapping[str, Any]],
    error_groups: Sequence[Mapping[str, Any]],
) -> str | None:
    """Write the three-sheet result workbook and return its path.

    Returns ``None`` when openpyxl is unavailable so the bridge can surface the
    same dependency message as before.
    """
    try:
        from openpyxl import Workbook
    except ImportError:
        return None

    os.makedirs(target_dir, exist_ok=True)
    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "分类汇总"
    summary_sheet.append(["发票分类", "数量", "金额合计"])

    category_summary: dict[str, dict[str, Any]] = {}
    for item in processed_invoices:
        category = str(item.get("category") or "未分类")
        bucket = category_summary.setdefault(category, {"count": 0, "amount": 0.0})
        bucket["count"] += 1
        bucket["amount"] += _parse_amount(item.get("amount", ""))

    if category_summary:
        for category in sorted(category_summary):
            bucket = category_summary[category]
            _append_text_row(
                summary_sheet,
                [category, bucket["count"], round(bucket["amount"], 2)],
                {0},
            )
    else:
        summary_sheet.append(["暂无成功记录", 0, 0.0])

    success_sheet = workbook.create_sheet("成功明细")
    success_sheet.append(
        ["日期", "金额", "销售方", "分类", "文件路径", "类目ID", "归类来源", "命中规则"]
    )
    for item in processed_invoices:
        _append_text_row(
            success_sheet,
            [
                item.get("date", ""),
                item.get("amount", ""),
                item.get("merchant", ""),
                item.get("category", ""),
                item.get("path", ""),
                item.get("category_id", ""),
                item.get("classification_source", ""),
                item.get("classification_rule", ""),
            ],
            set(range(8)),
        )

    error_sheet = workbook.create_sheet("异常记录")
    error_sheet.append(
        ["分组", "状态", "原因", "日期", "金额", "销售方", "文件名", "文件路径"]
    )
    for group in error_groups:
        for item in group.get("items", []):
            _append_text_row(
                error_sheet,
                [
                    group.get("label", ""),
                    item.get("status", ""),
                    item.get("reason", ""),
                    item.get("date", ""),
                    item.get("amount", ""),
                    item.get("merchant", ""),
                    item.get("name", ""),
                    item.get("path", ""),
                ],
                set(range(8)),
            )

    export_file = os.path.join(
        target_dir, f"结果明细_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    workbook.save(export_file)
    return export_file
