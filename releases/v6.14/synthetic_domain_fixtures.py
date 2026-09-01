"""v6.11 synthetic domain fixtures.

Controlled input → expected output contracts that verify domain rules
independently of real PDF parsing.  Each fixture is a self-contained
dict that can be run through ExpectedMemberResolver or CaptureDecisionReducer.
"""
from __future__ import annotations

from typing import Any

SYNTHETIC_FIXTURES: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------------
    "EXPLICIT_PARENT_STANDARD": {
        "description": "标准显式父项，4 个 NEW 成员，无外部注入",
        "resolution_mode": "EXPLICIT_PARENT",
        "presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION",
        "parent_present": True,
        "parent_label": "金融投资",
        "input_rows": [
            {"member_table": "fvtpl_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "other_debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "other_equity_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
        ],
        "expected": {
            "resolution_mode": "EXPLICIT_PARENT",
            "required_current_members": [
                "fvtpl_assets", "debt_investment",
                "other_debt_investment", "other_equity_investment",
            ],
            "outside_family_members": [],
            "comparative_only_members": [],
        },
    },

    # ------------------------------------------------------------------
    "EXPLICIT_PARENT_WITH_EXTERNAL_INVESTMENT_ROWS": {
        "description": "显式父项 + 同页定期存款/长期股权投资 → OUTSIDE_FAMILY",
        "resolution_mode": "EXPLICIT_PARENT",
        "presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION",
        "parent_present": True,
        "parent_label": "金融投资",
        "input_rows": [
            {"member_table": "fvtpl_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "other_debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "other_equity_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "time_deposits", "member_period_status": "OUTSIDE_FAMILY"},
            {"member_table": "long_term_equity", "member_period_status": "OUTSIDE_FAMILY"},
        ],
        "expected": {
            "resolution_mode": "EXPLICIT_PARENT",
            "required_current_members": [
                "fvtpl_assets", "debt_investment",
                "other_debt_investment", "other_equity_investment",
            ],
            "outside_family_members": ["time_deposits", "long_term_equity"],
        },
    },

    # ------------------------------------------------------------------
    "IMPLICIT_MEMBER_SET_SCATTERED": {
        "description": "无显式父项，成员散落 → IMPLICIT_MEMBER_SET",
        "resolution_mode": "IMPLICIT_MEMBER_SET",
        "presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION",
        "parent_present": False,
        "parent_label": None,
        "input_rows": [
            {"member_table": "legacy_fvtpl_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "time_deposits", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "available_for_sale_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "held_to_maturity_investments", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
        ],
        "expected": {
            "resolution_mode": "IMPLICIT_MEMBER_SET",
            "required_current_members": [
                "legacy_fvtpl_assets",
                "time_deposits",
                "available_for_sale_assets",
                "held_to_maturity_investments",
            ],
            "raw_parent_row_id": None,
            "raw_parent_label": None,
        },
    },

    # ------------------------------------------------------------------
    "MIXED_TRANSITION_CURRENT_VS_COMPARATIVE": {
        "description": "新旧准则过渡 → 新准则 ACTIVE，旧准则 COMPARATIVE_ONLY",
        "resolution_mode": "EXPLICIT_PARENT",
        "presentation_regime": "MIXED_TRANSITION_PRESENTATION",
        "parent_present": True,
        "parent_label": "金融投资",
        "input_rows": [
            {"member_table": "fvtpl_assets", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "other_debt_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "other_equity_investment", "member_period_status": "ACTIVE_CURRENT_PERIOD"},
            {"member_table": "available_for_sale_assets", "member_period_status": "COMPARATIVE_ONLY_LEGACY_MEMBER"},
            {"member_table": "held_to_maturity_investments", "member_period_status": "COMPARATIVE_ONLY_LEGACY_MEMBER"},
        ],
        "expected": {
            "resolution_mode": "EXPLICIT_PARENT",
            "required_current_members": [
                "fvtpl_assets", "debt_investment",
                "other_debt_investment", "other_equity_investment",
            ],
            "comparative_only_members": [
                "available_for_sale_assets", "held_to_maturity_investments",
            ],
        },
    },

    # ------------------------------------------------------------------
    "ANONYMOUS_NUMERIC_ROW": {
        "description": "空标签数值行默认 ANONYMOUS_NUMERIC_ROW，不阻断",
        "fixture_type": "capture_readiness",
        "evidence": {
            "boundary_status": "HARD_BOUNDARY_CONFIRMED",
            "stats": {
                "v69_header_topology": {"consistent": True},
                "v69_reconciliation": {"status": "PASS"},
                "mixed_cell_count": 0,
            },
            "rows": [
                {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
                 "cells": [{"raw": "100"}], "value": 100},
                {"row_order": 2, "row_role": "ANONYMOUS_NUMERIC_ROW",
                 "cells": [{"raw": "50"}], "value": 50},
            ],
            "header_dimension_status": "AUTO_CONFIRMED",
            "unit": "万元",
        },
        "expected": {
            "merge_ready": True,
            "unresolved_implicit_rows": 0,
        },
    },

    # ------------------------------------------------------------------
    "EXPLICIT_TOTAL_SUPPRESSES_IMPLICIT_TOTAL": {
        "description": "显式合计存在时，隐式合计被 suppress",
        "fixture_type": "capture_readiness",
        "evidence": {
            "boundary_status": "HARD_BOUNDARY_CONFIRMED",
            "stats": {
                "v69_header_topology": {"consistent": True},
                "v69_reconciliation": {"status": "PASS"},
                "mixed_cell_count": 0,
            },
            "rows": [
                {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
                 "cells": [{"raw": "100"}], "value": 100},
                {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
                 "cells": [{"raw": "100"}], "value": 100},
                {"row_order": 3, "row_role": "IMPLICIT_TOTAL",
                 "derived_status": "SUPPRESSED_BY_EXPLICIT_TOTAL",
                 "human_confirmed": False, "cells": [{"raw": "100"}], "value": 100},
            ],
            "header_dimension_status": "AUTO_CONFIRMED",
            "unit": "万元",
        },
        "expected": {
            "merge_ready": True,
            "unresolved_implicit_rows": 0,
        },
    },

    # ------------------------------------------------------------------
    "NATURAL_PAGE_END": {
        "description": "页末自然终止 → AUTO_HIGH_CONFIDENCE",
        "fixture_type": "boundary",
        "evidence": {
            "boundary_status": "",
            "stats": {
                "boundary_reason": "boundary_unresolved",
                "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
                "v69_header_topology": {"consistent": True},
                "v69_reconciliation": {"status": "PASS"},
                "roi": {"end_y": 800},
                "engine": "v6.11",
            },
            "rows": [
                {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
                 "cells": [{"raw": "100"}], "value": 100},
                {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
                 "cells": [{"raw": "100"}], "value": 100,
                 "bbox": {"y1": 780}},
            ],
            "warnings": [],
        },
        "expected": {
            "boundary_status": "AUTO_HIGH_CONFIDENCE",
            "merge_ready": True,
        },
    },

    # ------------------------------------------------------------------
    "SAME_NOTE_DIFFERENT_TABLE_BLOCK": {
        "description": "同附注不同表块 → AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING",
        "fixture_type": "boundary",
        "evidence": {
            "boundary_status": "",
            "stats": {
                "boundary_reason": "boundary_unresolved",
                "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
                "v69_header_topology": {"consistent": True},
                "v69_reconciliation": {"status": "PASS"},
                "roi": {"end_y": 800},
                "engine": "v6.11",
            },
            "rows": [
                {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
                 "cells": [{"raw": "100"}], "value": 100},
                {"row_order": 2, "row_role": "TOTAL", "raw_item": "合计",
                 "cells": [{"raw": "100"}], "value": 100,
                 "bbox": {"y1": 400}},
                {"row_order": 3, "row_role": "SECTION", "raw_item": "信用损失准备",
                 "cells": []},
            ],
            "warnings": [],
        },
        "expected": {
            "boundary_status": "AUTO_ACCEPTED_WITH_NON_BLOCKING_WARNING",
            "merge_ready": True,
        },
    },

    # ------------------------------------------------------------------
    "TRUE_CROSS_PAGE_CONTINUATION": {
        "description": "真实跨页续表 → REVIEW_REQUIRED",
        "fixture_type": "boundary",
        "evidence": {
            "boundary_status": "",
            "stats": {
                "boundary_reason": "max_pages",
                "boundary_evidence": {"method": "NO_PEER_HEADING_FOUND"},
                "v69_header_topology": {"consistent": True},
                "v69_reconciliation": {"status": "PASS"},
                "roi": {"end_y": 800},
                "engine": "v6.11",
            },
            "rows": [
                {"row_order": 1, "row_role": "DETAIL", "raw_item": "上市",
                 "cells": [{"raw": "100"}], "value": 100,
                 "bbox": {"y1": 780}},
            ],
            "warnings": ["跨页续表"],
        },
        "expected": {
            "boundary_status": "REVIEW_REQUIRED",
            "merge_ready": False,
        },
    },

    # ------------------------------------------------------------------
    "IMAGE_DOMINANT_STATEMENT_DISCOVERY": {
        "description": "图像型主表 → OCR 定位结构但不生成金额",
        "fixture_type": "ocr_contract",
        "input_candidate": {
            "statement_type": "BALANCE_SHEET",
            "scope": "CONSOLIDATED",
            "statement_pdf_page_index": 3,
            "source_table_title": "合并资产负债表",
            "statement_item": "债权投资",
            "member_table": "debt_investment",
            "member_period_status": "ACTIVE_CURRENT_PERIOD",
            "statement_amount_raw": ["2,000"],
            "statement_amount_normalized": ["2000"],
            "statement_amounts": ["2,000"],
            "values": ["2,000"],
            "amount_source_present": True,
            "ocr_used": True,
            "candidate_note_pdf_page_index": 9,
            "confidence": 0.91,
            "evidence": {
                "ocr_token_provenance": {
                    "raw_numeric_tokens": ["2,000"],
                    "usable_as_amount": False,
                },
            },
        },
        "expected": {
            "ocr_only_locates_structure": True,
            "ocr_does_not_generate_amounts": True,
            "amounts_from_pdf_visual_evidence": True,
        },
    },
}


def run_fixture(fixture_id: str) -> dict[str, Any]:
    """Execute a single fixture through the appropriate resolver."""
    fixture = SYNTHETIC_FIXTURES.get(fixture_id)
    if not fixture:
        return {"status": "NOT_FOUND", "fixture_id": fixture_id}

    ftype = fixture.get("fixture_type", "member_resolution")

    if ftype == "member_resolution":
        from expected_member_resolver import resolve_expected_members
        result = resolve_expected_members(
            resolution_mode=fixture["resolution_mode"],
            presentation_regime=fixture["presentation_regime"],
            report_year="2024",
            statement_scope="CONSOLIDATED",
            source_parent_boundary=(
                {"label": fixture["parent_label"]}
                if fixture.get("parent_present") else None
            ),
            definition_version="V1",
            registry_members=_registry_members(),
            actual_statement_rows=fixture["input_rows"],
        )
        expected = fixture["expected"]
        return {
            "fixture_id": fixture_id,
            "status": "PASS" if (
                set(result.get("required_current_members", []))
                == set(expected.get("required_current_members", []))
                and set(result.get("outside_family_members", []))
                == set(expected.get("outside_family_members", []))
                and set(result.get("comparative_only_members", []))
                == set(expected.get("comparative_only_members", []))
            ) else "FAIL",
            "expected": expected,
            "actual": {
                "required_current_members": result.get("required_current_members"),
                "outside_family_members": result.get("outside_family_members"),
                "comparative_only_members": result.get("comparative_only_members"),
            },
        }

    if ftype == "capture_readiness":
        from capture_library import capture_readiness
        readiness = capture_readiness(fixture["evidence"])
        expected = fixture["expected"]
        return {
            "fixture_id": fixture_id,
            "status": "PASS" if (
                readiness.get("merge_ready") == expected.get("merge_ready")
            ) else "FAIL",
            "expected": expected,
            "actual": {
                "merge_ready": readiness.get("merge_ready"),
                "unresolved_implicit_rows": readiness.get("unresolved_implicit_rows"),
            },
        }

    if ftype == "boundary":
        from capture_library import derive_boundary_status, capture_readiness
        boundary = derive_boundary_status(fixture["evidence"])
        readiness = capture_readiness(fixture["evidence"])
        expected = fixture["expected"]
        return {
            "fixture_id": fixture_id,
            "status": "PASS" if (
                boundary == expected.get("boundary_status")
                and readiness.get("merge_ready") == expected.get("merge_ready")
            ) else "FAIL",
            "expected": expected,
            "actual": {
                "boundary_status": boundary,
                "merge_ready": readiness.get("merge_ready"),
            },
        }

    if ftype == "ocr_contract":
        from generic_structure_parser import GenericStructureParser

        occurrences = GenericStructureParser().parse(
            [fixture["input_candidate"]],
            strategy="STATEMENT_PARENT_TO_MULTI_NOTE",
            family_id="financial_investment",
            display_name="金融投资",
        )
        children = occurrences[0].get("child_rows", []) if occurrences else []
        child = children[0] if children else {}
        actual = {
            "ocr_only_locates_structure": bool(
                child.get("ocr_used")
                and child.get("candidate_note_pdf_page_index") == 9
                and child.get("ocr_token_provenance")
            ),
            "ocr_does_not_generate_amounts": bool(
                child
                and not child.get("statement_amount_raw")
                and not child.get("statement_amount_normalized")
                and not child.get("statement_amounts")
                and not child.get("values")
                and child.get("amount_source_present") is False
            ),
            "amounts_from_pdf_visual_evidence": bool(
                child.get("native_value_geometry_present") is False
                and child.get("value_evidence_status")
                == "REJECTED_OCR_WITHOUT_NATIVE_GEOMETRY"
            ),
        }
        expected = fixture["expected"]
        return {
            "fixture_id": fixture_id,
            "status": "PASS" if actual == expected else "FAIL",
            "expected": expected,
            "actual": actual,
        }

    return {
        "status": "FAIL",
        "fixture_id": fixture_id,
        "reason": f"Unknown fixture_type={ftype}",
    }


def _registry_members() -> list[dict[str, Any]]:
    return [
        {"member_id": "fvtpl_assets", "payload": {"presentation_regime": "NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION"}},
        {"member_id": "debt_investment", "payload": {}},
        {"member_id": "other_debt_investment", "payload": {}},
        {"member_id": "other_equity_investment", "payload": {}},
        {"member_id": "legacy_fvtpl_assets", "payload": {"presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"}},
        {"member_id": "available_for_sale_assets", "payload": {"presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"}},
        {"member_id": "held_to_maturity_investments", "payload": {"presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"}},
        {"member_id": "time_deposits", "payload": {"presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"}},
        {"member_id": "long_term_equity", "payload": {"presentation_regime": "LEGACY_FINANCIAL_ASSET_CLASSIFICATION"}},
    ]
