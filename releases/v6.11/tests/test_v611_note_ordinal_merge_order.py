"""v6.11 note-ordinal merge ordering contracts (selected reference year)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from table_merge import (  # noqa: E402
    NOTE_ORDINAL_ORDER_POLICY,
    refresh_merge_project,
    write_merge_outputs,
)


def _raw_long() -> pd.DataFrame:
    rows = []
    specs = [
        # (member, year, run_id, note_reference, member_order, value)
        ("legacy_loans", "2023", "CAP_A2023", "附注十-8", 2, 100.0),
        ("legacy_loans", "2024", "CAP_A2024", "附注十一-8", 2, 110.0),
        ("fvtpl_assets", "2023", "CAP_B2023", "附注十-6", 1, 200.0),
        ("fvtpl_assets", "2024", "CAP_B2024", "附注十一-6", 1, 210.0),
        ("other_debt_investment", "2025", "CAP_C2025", "附注十-10", 3, 300.0),
    ]
    for member, year, run_id, note_ref, order, value in specs:
        rows.append({
            "capture_run_id": run_id,
            "member_table_order": order,
            "row_order": 1,
            "company": "中国平安",
            "document_year": year,
            "table_id": "financial_investment",
            "table_family": "金融投资",
            "member_table": member,
            "member_table_role": "NOTE_DETAIL",
            "source_table_title": "金融投资附注",
            "note_reference": note_ref,
            "source_pdf": f"{year}.pdf",
            "container_id": "",
            "table_block_id": "",
            "block_order": -1,
            "classification_axis": "UNRESOLVED",
            "block_role": "UNRESOLVED",
            "block_terminal_type": "UNRESOLVED",
            "parent_section": "金融投资",
            "normalized_item": "合计",
            "raw_item": "合计",
            "page": 100,
            "row_path": f"金融投资 / {member} / 合计",
            "source_key": "合计",
            "report_year": year,
            "data_year": year,
            "year": year,
            "statement_scope": "CONSOLIDATED",
            "restated_flag": False,
            "period_type": "ANNUAL",
            "currency": "CNY",
            "currency_unit": "CNY_MILLION",
            "unit": "百万元",
            "measure": "",
            "value": value,
        })
    return pd.DataFrame(rows)


def _mapping_queue() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "source_key", "canonical_section", "canonical_item",
            "category", "mapping_status", "mapping_note",
        ],
    )


def _manifest(order_policy: str | None, reference_year: str | None) -> dict:
    manifest = {
        "version": "v6.7",
        "table_id": "financial_investment",
        "sources": [
            {
                "capture_run_id": "CAP_A2023",
                "member_table": "legacy_loans",
                "member_table_order": 2,
                "note_reference": "附注十-8",
                "document_year": "2023",
            },
            {
                "capture_run_id": "CAP_A2024",
                "member_table": "legacy_loans",
                "member_table_order": 2,
                "note_reference": "附注十一-8",
                "document_year": "2024",
            },
            {
                "capture_run_id": "CAP_B2023",
                "member_table": "fvtpl_assets",
                "member_table_order": 1,
                "note_reference": "附注十-6",
                "document_year": "2023",
            },
            {
                "capture_run_id": "CAP_B2024",
                "member_table": "fvtpl_assets",
                "member_table_order": 1,
                "note_reference": "附注十一-6",
                "document_year": "2024",
            },
            {
                "capture_run_id": "CAP_C2025",
                "member_table": "other_debt_investment",
                "member_table_order": 3,
                "note_reference": "附注十-10",
                "document_year": "2025",
            },
        ],
        "reference_capture_run_id": "CAP_A2023",
    }
    if order_policy:
        manifest["order_policy"] = order_policy
    if reference_year:
        manifest["reference_report_year"] = reference_year
    return manifest


def _order_members(output_dir: Path) -> list[str]:
    order = pd.read_csv(output_dir / "merge_structural_order.csv")
    return order["member_table"].astype(str).tolist()


def test_note_ordinal_policy_orders_members_by_selected_year_notes(
    tmp_path: Path,
):
    output_dir = tmp_path / "merge"
    write_merge_outputs(
        output_dir=output_dir,
        manifest=_manifest(
            NOTE_ORDINAL_ORDER_POLICY, "2023",
        ),
        raw_long=_raw_long(),
        mapping_queue=_mapping_queue(),
        taxonomy_path=None,
    )
    order = pd.read_csv(output_dir / "merge_structural_order.csv")
    assert order["member_table"].astype(str).tolist() == [
        "fvtpl_assets",       # 附注十-6
        "legacy_loans",       # 附注十-8
        "other_debt_investment",  # no 2023 capture -> appended last
    ]
    assert order["note_ordinal"].tolist() == [6, 8, None] or order[
        "note_ordinal"
    ].fillna(-1).astype(int).tolist() == [6, 8, -1]
    assert order["order_source"].iloc[0].startswith(
        "NOTE_ORDINAL:附注十-6:2023"
    )


def test_legacy_reference_policy_remains_default(tmp_path: Path):
    output_dir = tmp_path / "merge"
    write_merge_outputs(
        output_dir=output_dir,
        manifest=_manifest(None, None),
        raw_long=_raw_long(),
        mapping_queue=_mapping_queue(),
        taxonomy_path=None,
    )
    order = pd.read_csv(output_dir / "merge_structural_order.csv")
    # Legacy policy: reference capture CAP_A2023 order first (legacy_loans),
    # then appended keys.
    assert order["member_table"].astype(str).tolist()[0] == "legacy_loans"
    assert order["note_ordinal"].isna().all()


def test_refresh_persists_note_ordinal_policy(tmp_path: Path):
    output_dir = tmp_path / "merge"
    write_merge_outputs(
        output_dir=output_dir,
        manifest=_manifest(None, None),
        raw_long=_raw_long(),
        mapping_queue=_mapping_queue(),
        taxonomy_path=None,
    )
    refresh_merge_project(
        output_dir=output_dir,
        order_policy=NOTE_ORDINAL_ORDER_POLICY,
        reference_report_year="2023",
    )
    manifest = json.loads(
        (output_dir / "merge_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["order_policy"] == NOTE_ORDINAL_ORDER_POLICY
    assert manifest["reference_report_year"] == "2023"
    assert _order_members(output_dir)[0] == "fvtpl_assets"


def test_app_creation_ui_offers_note_ordinal_ordering():
    """The merge-creation page must expose the by-year ordering option."""
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "按年份附注号排序" in app_source
    assert "merge_order_policy_selector" in app_source
    assert "merge_order_reference_year" in app_source
    assert "order_policy=order_policy" in app_source


def test_detail_note_order_refresh_keeps_current_page_context():
    """Updated outputs are read later in the same run; no full rerun is needed."""
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    action_start = app_source.index('key=f"apply_note_order_{merge_name}"')
    action_end = app_source.index("except Exception as exc:", action_start)
    action_source = app_source[action_start:action_end]
    assert "refresh_merge_project(" in action_source
    assert "st.rerun()" not in action_source
