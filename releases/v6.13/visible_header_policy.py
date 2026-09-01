"""Adaptive presentation policy for Canonical Research Wide.

Long observations retain every dimension.  This module decides only which
dimensions are metadata and which must be visible in a Wide header.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from html import escape
import pandas as pd

OBSERVATION_DIMENSIONS = [
    "company", "report_year", "period_label", "period_identity",
    "period_year", "period_month", "period_day", "period_precision",
    "period_date", "data_year", "statement_scope", "restated_flag",
    "period_type", "currency", "currency_unit", "measure",
]

DISPLAY_ORDER = [
    "company", "report_year", "period_label", "data_year", "statement_scope",
    "restated_flag", "period_type", "currency", "currency_unit", "measure",
]

DISPLAY_NAMES = {"company":"公司", "report_year":"报告年", "period_label":"期间", "data_year":"数据年", "statement_scope":"口径", "restated_flag":"重述", "period_type":"报告类型", "currency":"币种", "currency_unit":"单位", "measure":"度量"}

def _clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)): return ""
    return str(value).strip()

def _flag(value: Any) -> bool:
    return _clean(value).lower() in {"1","true","yes","已重述","重述","经重述"}

def display_value(dimension: str, value: Any) -> str:
    text=_clean(value)
    if dimension == "report_year": return f"{text}年报" if text else ""
    if dimension == "data_year": return f"{text}" if text else ""
    if dimension == "period_label": return text
    if dimension == "restated_flag": return "已重述" if _flag(value) else ""
    if dimension == "statement_scope": return {"CONSOLIDATED":"合并", "COMPANY":"公司"}.get(text,text)
    if dimension == "period_type": return {"ANNUAL":"年度", "INTERIM":"中期", "QUARTERLY":"季度"}.get(text,text)
    if dimension == "currency_unit": return {"CNY_MILLION":"人民币百万元", "CNY":"人民币元", "CNY_THOUSAND":"人民币千元", "CNY_TEN_THOUSAND":"人民币万元", "CNY_HUNDRED_MILLION":"人民币亿元"}.get(text,text)
    return text

@dataclass(frozen=True)
class VisibleHeaderDimensionPolicy:
    metadata_dimensions: tuple[str, ...]
    visible_header_dimensions: tuple[str, ...]
    display_order: tuple[str, ...]
    metadata_values: dict[str, str]

    @classmethod
    def from_column_dimensions(cls, dimensions: pd.DataFrame) -> "VisibleHeaderDimensionPolicy":
        unique={}
        for dim in OBSERVATION_DIMENSIONS:
            values={_clean(v) for v in (dimensions[dim] if dim in dimensions else []) if _clean(v)}
            unique[dim]=values
        metadata=[]; visible=[]; values={}
        for dim in DISPLAY_ORDER:
            count=len(unique[dim])
            # Filing year and the normalized point-period remain visible even
            # when a single source column is selected.
            if dim == "report_year":
                visible.append(dim); continue
            if dim == "period_label":
                if count:
                    visible.append(dim)
                continue
            if dim == "data_year":
                # Legacy V3 assets have no period_label.  Preserve their
                # readable year header until they are rematerialized through
                # the V4 compatibility adapter.
                if not unique["period_label"]:
                    visible.append(dim)
                continue
            # Restatement is normally rendered as a data-year suffix.  It only
            # needs its own level when original and restated observations would
            # otherwise share every visible time/context dimension.
            if dim == "restated_flag":
                compare = [
                    "company", "report_year", "period_label", "statement_scope",
                    "period_type", "currency", "currency_unit", "measure",
                ]
                comparable = [column for column in compare if column in dimensions]
                needs_level = False
                if comparable and dim in dimensions:
                    grouped = dimensions.groupby(comparable, dropna=False)[dim].nunique(dropna=False)
                    needs_level = bool((grouped > 1).any())
                if needs_level: visible.append(dim)
                elif count == 1: metadata.append(dim); values[dim]=display_value(dim,next(iter(unique[dim])))
                continue
            if count <= 1:
                metadata.append(dim)
                if count: values[dim]=display_value(dim,next(iter(unique[dim])))
            else:
                visible.append(dim)
        return cls(tuple(metadata),tuple(visible),tuple(DISPLAY_ORDER),values)

    def label_for_column(self, row: dict[str, Any]) -> dict[str, str]:
        labels={dim:display_value(dim,row.get(dim)) for dim in self.visible_header_dimensions}
        # In the common single-company annual view, present restatement as a
        # suffix of data_year rather than a redundant third row.
        if "restated_flag" not in self.visible_header_dimensions and _flag(row.get("restated_flag")) and "period_label" in labels:
            labels["period_label"]=(labels["period_label"] + "（已重述）").strip()
        return labels


def adaptive_wide_preview_html(
    wide: pd.DataFrame,
    dimensions: pd.DataFrame,
    *,
    max_rows: int = 200,
) -> tuple[str, VisibleHeaderDimensionPolicy]:
    """Render a browser-safe, true multi-level Research Wide preview.

    Streamlit's dataframe grid flattens MultiIndex columns in several runtime
    versions.  The preview therefore emits explicit HTML header rows while the
    CSV remains machine-oriented ``COL_xxxxx`` plus ``column_dimensions.csv``.
    """
    policy = VisibleHeaderDimensionPolicy.from_column_dimensions(dimensions)
    if wide.empty or dimensions.empty or "column_id" not in dimensions:
        return "<p>暂无可展示的自适应宽表。</p>", policy

    dimension_rows = {
        str(row.get("column_id")): row
        for row in dimensions.to_dict("records")
        if str(row.get("column_id") or "")
    }
    value_columns = [column for column in wide.columns if str(column) in dimension_rows]
    fixed_columns = [column for column in wide.columns if column not in value_columns]
    if not value_columns:
        return "<p>当前宽表尚未升级为 COL_xxxxx + column_dimensions 契约。</p>", policy

    labels = [policy.label_for_column(dimension_rows[str(column)]) for column in value_columns]
    header_dimensions = list(policy.visible_header_dimensions) or ["period_label"]

    def cells_for_level(dimension: str) -> list[tuple[str, int]]:
        values = [str(label.get(dimension) or "") for label in labels]
        groups: list[tuple[str, int]] = []
        start = 0
        while start < len(values):
            prefix = tuple(
                str(labels[start].get(parent) or "")
                for parent in header_dimensions[:header_dimensions.index(dimension)]
            )
            end = start + 1
            while end < len(values):
                candidate_prefix = tuple(
                    str(labels[end].get(parent) or "")
                    for parent in header_dimensions[:header_dimensions.index(dimension)]
                )
                if candidate_prefix != prefix or values[end] != values[start]:
                    break
                end += 1
            groups.append((values[start], end - start))
            start = end
        return groups

    lines = [
        '<div style="overflow:auto;max-height:680px;border:1px solid #e5e7eb;border-radius:8px">',
        '<table style="border-collapse:collapse;width:100%;font-size:13px">',
        '<thead>',
    ]
    for level_index, dimension in enumerate(header_dimensions):
        lines.append('<tr>')
        if level_index == 0:
            for column in fixed_columns:
                lines.append(
                    '<th rowspan="%d" style="position:sticky;top:0;background:#f8fafc;'
                    'border:1px solid #d1d5db;padding:6px;text-align:left">%s</th>'
                    % (len(header_dimensions), escape(str(column)))
                )
        for value, span in cells_for_level(dimension):
            text = value or "—"
            lines.append(
                '<th colspan="%d" style="background:#e0f2fe;border:1px solid #d1d5db;'
                'padding:6px;text-align:center;white-space:nowrap">%s</th>'
                % (span, escape(text))
            )
        lines.append('</tr>')
    lines.append('</thead><tbody>')
    for _, row in wide.head(max_rows).iterrows():
        lines.append('<tr>')
        for column in fixed_columns:
            lines.append('<td style="border:1px solid #e5e7eb;padding:5px;text-align:left">%s</td>' % escape(str(row.get(column, "") if pd.notna(row.get(column, "")) else "")))
        for column in value_columns:
            value = row.get(column, "")
            lines.append('<td style="border:1px solid #e5e7eb;padding:5px;text-align:right">%s</td>' % escape(str(value if pd.notna(value) else "")))
        lines.append('</tr>')
    lines.append('</tbody></table></div>')
    if len(wide) > max_rows:
        lines.append('<p style="color:#6b7280">预览仅显示前 %d 行；下载/Excel 导出保留完整数据。</p>' % max_rows)
    return "".join(lines), policy


def adaptive_wide_interactive_frame(
    wide: pd.DataFrame,
    dimensions: pd.DataFrame,
    *,
    max_rows: int | None = None,
) -> tuple[pd.DataFrame, VisibleHeaderDimensionPolicy]:
    """Return the native-grid view using the same policy as the HTML preview.

    Streamlit's native dataframe supplies the familiar asset-management toolbar,
    but it cannot render a MultiIndex header reliably.  This view therefore
    flattens only the *display* labels; canonical CSV identity remains COL ids.
    """
    policy = VisibleHeaderDimensionPolicy.from_column_dimensions(dimensions)
    if wide.empty or dimensions.empty or "column_id" not in dimensions:
        return wide.copy(), policy
    dimension_rows = {
        str(row.get("column_id")): row
        for row in dimensions.to_dict("records")
        if str(row.get("column_id") or "")
    }
    value_columns = [column for column in wide.columns if str(column) in dimension_rows]
    if not value_columns:
        return wide.copy(), policy

    output = wide.copy()
    used_labels: dict[str, int] = {}
    rename: dict[object, str] = {}
    for column in value_columns:
        labels = policy.label_for_column(dimension_rows[str(column)])
        label = " / ".join(
            value for dimension in policy.visible_header_dimensions
            if (value := str(labels.get(dimension) or ""))
        ) or str(column)
        used_labels[label] = used_labels.get(label, 0) + 1
        # A duplicate presentation label must stay distinguishable in the
        # native grid; the durable identity remains column_dimensions.csv.
        if used_labels[label] > 1:
            label = f"{label} [{column}]"
        rename[column] = label
    output = output.rename(columns=rename)
    if max_rows is not None:
        output = output.head(max_rows)
    return output, policy
