from pathlib import Path

from anchor_candidate_selection import score_anchor_candidate
from statement_anchor_evidence_v2 import build_statement_anchor_evidence_v2, scope_from_statement_text
from services.discovery_service import DiscoveryService


ROOT = Path(r"C:\dev\AXA_research")


def test_scope_has_no_page_order_fallback():
    assert scope_from_statement_text("合并 资产负债表")[0] == "CONSOLIDATED"
    assert scope_from_statement_text("母公司 资产负债表")[0] == "PARENT_COMPANY"
    assert scope_from_statement_text("资产负债表")[0] == "UNKNOWN"


def test_picc_2024_v2_binds_periods_members_notes_and_amount_geometry():
    evidence = build_statement_anchor_evidence_v2(
        ROOT / "docu" / "中国人保2024年年度报告.pdf", 142, 2024, parent_aliases=("金融投资",),
    ).payload()
    assert evidence["source_statement_scope"] == "CONSOLIDATED"
    assert [column["period_year"] for column in evidence["period_columns"]] == [2024, 2023]
    members = {row["member_table"]: row for row in evidence["members"]}
    assert set(members) == {"fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment"}
    assert [cell["value"] for cell in members["fvtpl_assets"]["amount_cells"]] == [317670.0, 383020.0]
    assert members["other_debt_investment"]["note_reference"] == "5"
    assert evidence["native_value_geometry_present"] is True


def test_cpic_2023_transition_rows_keep_physical_note_and_amount_pairs():
    evidence = build_statement_anchor_evidence_v2(
        ROOT / "docu" / "中国太保2023年报.pdf", 144, 2023,
        parent_aliases=("金融投资",),
    ).payload()
    fvtpl_rows = [
        row for row in evidence["members"]
        if row["member_table"] in {"fvtpl_assets", "legacy_fvtpl_assets"}
    ]
    by_member = {row["member_table"]: row for row in fvtpl_rows}
    assert set(by_member) == {"fvtpl_assets", "legacy_fvtpl_assets"}
    assert by_member["fvtpl_assets"]["source_row_id"] != by_member["legacy_fvtpl_assets"]["source_row_id"]
    assert by_member["fvtpl_assets"]["note_reference"] == "10"
    assert [
        cell["value"] for cell in by_member["fvtpl_assets"]["amount_cells"]
        if cell["period_role"] == "CURRENT"
    ] == [581602.0]
    assert by_member["legacy_fvtpl_assets"]["note_reference"] == "2"
    assert by_member["legacy_fvtpl_assets"]["member_period_status"] == "COMPARATIVE_ONLY_LEGACY_MEMBER"
    assert evidence["required_current_member_status_valid"] is True


def test_parent_scope_is_a_hard_gate_not_a_small_penalty():
    candidate = {
        "pdf_id": "fixture.pdf", "scope": "PARENT_COMPANY", "source_statement_scope": "PARENT_COMPANY",
        "report_year": "2025", "statement_type": "BALANCE_SHEET", "parent_text": "金融投资",
        "display_name": "金融投资", "child_rows": [{"value": 1}] * 4,
        "evidence": {
            "schema_version": "STATEMENT_ANCHOR_EVIDENCE_V2", "source_statement_scope": "PARENT_COMPANY",
            "period_columns": [{"period_year": 2025, "period_role": "CURRENT"}], "unit": "人民币百万元",
            "native_value_geometry_present": True,
            "members": [{"member_table": value} for value in ("fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment")],
        },
    }
    result = score_anchor_candidate(candidate, {"scope_preference": "CONSOLIDATED", "required_member_tables": ["fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment"]})
    assert result["hard_gate_results"]["scope_compatible"] is False
    assert result["hard_gates_passed"] is False


def test_ranking_consumes_v2_and_excludes_picc_parent_statement(tmp_path):
    class Registry:
        def save_anchor_scores(self, rows): self.rows = rows
        def sync_anchor_review_queue(self, result): self.result = result
    registry = Registry()
    pdf = ROOT / "docu" / "中国人保2024年年度报告.pdf"
    rows = []
    for page in (142, 144):
        rows.append({
            "occurrence_id": f"PICC_{page}", "pdf_id": str(pdf), "report_year": "2024",
            "scope": "CONSOLIDATED", "table_family": "FINANCIAL_INVESTMENT_V1", "statement_type": "BALANCE_SHEET",
            "display_name": "金融投资", "parent_text": "金融投资", "statement_pdf_page_index": page,
            "child_rows": [{"member_table": member, "item": member, "value": 1} for member in ("fvtpl_assets", "debt_investment", "other_debt_investment", "other_equity_investment")],
            "evidence": {},
        })
    ranked = DiscoveryService(registry, tmp_path).rank_anchor_candidates(rows, scope_preference="CONSOLIDATED", required_scopes=["CONSOLIDATED"])
    assert [row["statement_pdf_page_index"] for row in ranked["candidates"]] == [142]
    assert ranked["preselected_ids"] == ["PICC_142"]
    assert ranked["excluded_scope_candidates"][0]["source_statement_scope"] == "PARENT_COMPANY"


def test_native_v2_ranking_persists_the_exact_review_candidate(tmp_path):
    class Registry:
        def __init__(self):
            self.occurrences = {}

        def save_occurrence(self, row):
            self.occurrences[row["occurrence_id"]] = dict(row)
            return dict(row)

        def get_occurrence(self, occurrence_id):
            row = self.occurrences.get(occurrence_id)
            return dict(row) if row else None

        def save_anchor_scores(self, rows):
            self.rows = list(rows)

        def sync_anchor_review_queue(self, result):
            self.result = result

    registry = Registry()
    pdf = ROOT / "docu" / "中国人保2024年年度报告.pdf"
    original = {
        "occurrence_id": "PICC_2024_NATIVE_ORIGINAL",
        "pdf_id": str(pdf),
        "report_year": "2024",
        "scope": "CONSOLIDATED",
        "table_family": "FINANCIAL_INVESTMENT_V1",
        "statement_type": "BALANCE_SHEET",
        "display_name": "金融投资",
        "parent_text": "金融投资",
        "statement_pdf_page_index": 142,
        "child_rows": [
            {"member_table": member, "item": member, "value": 1}
            for member in (
                "fvtpl_assets",
                "debt_investment",
                "other_debt_investment",
                "other_equity_investment",
            )
        ],
        "evidence": {},
    }
    ranked = DiscoveryService(registry, tmp_path).rank_anchor_candidates(
        [original],
        scope_preference="CONSOLIDATED",
        required_scopes=["CONSOLIDATED"],
    )
    candidate = ranked["candidates"][0]
    assert candidate["occurrence_id"].startswith("OCC_EVD_")
    assert ranked["preselected_ids"] == [candidate["occurrence_id"]]
    persisted = registry.occurrences[candidate["occurrence_id"]]
    assert persisted["evidence"]["schema_version"] == "STATEMENT_ANCHOR_EVIDENCE_V2"
    assert persisted["evidence"]["evidence_revision_kind"] == "NATIVE_V2"
    assert persisted["evidence"]["evidence_revision_parent_occurrence_id"] == original["occurrence_id"]
    assert persisted["evidence"]["value_geometry_verified"] is True
    assert persisted["child_rows"] == candidate["child_rows"]
