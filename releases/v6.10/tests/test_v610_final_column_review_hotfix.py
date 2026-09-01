from __future__ import annotations

import json
from pathlib import Path

from final_data_review import review_final_data_columns


ROOT=Path(__file__).resolve().parents[1]


def test_structured_cells_are_counted_for_last_column():
    result={
        "columns":[{"year":"2025"},{"year":"2024"}],
        "rows":[
            {
                "row_order":1,"row_type":"DETAIL",
                "cells":[
                    {"column_ordinal":0,"raw":"100"},
                    {"column_ordinal":1,"raw":"90"},
                ],
            },
            {
                "row_order":2,"row_type":"IMPLICIT_TOTAL",
                "cells":[
                    {"column_ordinal":0,"raw":"100"},
                    {"column_ordinal":1,"raw":"90"},
                ],
            },
        ],
    }
    review=review_final_data_columns(result)
    assert review["last_column_check"]=={
        "status":"PASS",
        "last_column":review["last_column_check"]["last_column"],
        "rows_with_last_token":1,
        "row_count":1,
        "excluded_derived_rows":1,
        "excluded_non_value_rows":0,
    }
    assert not any(
        issue["reason_code"]=="LAST_COLUMN_MAPPING_UNCERTAIN"
        for issue in review["issues"]
    )


def test_real_pingan_capture_has_complete_last_column_when_available():
    path=Path(
        r"C:\Users\HzhJa\FinancialMetricResolverData\table_captures"
        r"\中国平安2025年报__债权投资__20260728T133636_748377"
        r"\table_capture_result.json"
    )
    if not path.exists():
        return
    review=review_final_data_columns(json.loads(path.read_text(encoding="utf-8")))
    assert review["last_column_check"]["status"]=="PASS"
    assert review["last_column_check"]["rows_with_last_token"]==11
    assert review["last_column_check"]["row_count"]==11
    assert review["last_column_check"]["excluded_derived_rows"]==1
    assert review["last_column_check"]["excluded_non_value_rows"]==1


def test_final_review_ui_has_an_audited_override_action():
    source=(ROOT/"components/capture_inspection_panel.py").read_text(encoding="utf-8")
    assert "人工覆盖确认警告" in source
    assert 'decision="OVERRIDDEN"' in source
    assert '"machine_issues"' in source


def test_recheck_closes_stale_machine_issues():
    source=(ROOT/"services/review_task_service.py").read_text(encoding="utf-8")
    assert "MACHINE_RECHECK_CLEARED" in source
    assert "active_codes" in source


def test_review_required_registered_capture_can_be_current():
    source=(ROOT/"repositories/asset_governance_repository.py").read_text(encoding="utf-8")
    assert 'make_current = bool(registration_status == "REGISTERED")' in source
    assert "currentless_assets_repaired" in source


def test_boundary_warning_has_a_real_human_review_action():
    panel=(ROOT/"components/capture_inspection_panel.py").read_text(encoding="utf-8")
    tasks=(ROOT/"services/review_task_service.py").read_text(encoding="utf-8")
    assert "确认最后有效行并重建正式输出" in panel
    assert "apply_boundary" in panel
    assert 'task_type="PDF_BOUNDARY_REVIEW"' in panel
    assert "PDF_BOUNDARY_UNCERTAIN" in tasks
