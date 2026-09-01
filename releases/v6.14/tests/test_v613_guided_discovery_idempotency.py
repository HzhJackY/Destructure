from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from discovery_registry import DiscoveryRegistry
from guided_workflow_ui import _guided_discovery_failure_rows
from metadata_registry import MetadataRegistry


def _candidate() -> dict:
    return {
        "discovery_id": "DPT_STABLE_CANDIDATE",
        "pdf_id": r"C:\reports\中国太保2024年报.pdf",
        "company": "中国太保",
        "report_year": "2024",
        "filing_type": "ANNUAL_REPORT",
        "statement_type": "NOTE_SECTION",
        "display_name": "投资组合",
        "table_family": "investment_portfolio",
        "member_table": "portfolio_by_category",
        "source_table_title": "投资组合（按投资品种）",
        "statement_pdf_page_index": 48,
        "locator_method": "DIRECT_PORTFOLIO_TABLES",
        "confidence": 0.97,
        "evidence": {
            "strategy": "DIRECT_PORTFOLIO_TABLES",
            "disclosure_topology": "DIRECT_COMPOUND_TABLE",
        },
    }


def test_machine_discovery_replay_is_idempotent(tmp_path: Path) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    discoveries = DiscoveryRegistry(registry)

    first = discoveries.save_machine(_candidate())
    second = discoveries.save_machine(_candidate())

    assert second["discovery_id"] == first["discovery_id"]
    assert second["created_at"] == first["created_at"]
    with registry.connect() as conn:
        rows = conn.execute(
            "SELECT discovery_id, created_at FROM machine_discoveries"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["discovery_id"] == "DPT_STABLE_CANDIDATE"


def test_machine_discovery_id_collision_with_changed_evidence_fails_closed(tmp_path: Path) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    discoveries = DiscoveryRegistry(registry)
    discoveries.save_machine(_candidate())
    changed = _candidate()
    changed["report_year"] = "2025"

    with pytest.raises(sqlite3.IntegrityError, match="MACHINE_DISCOVERY_IDENTITY_CONFLICT"):
        discoveries.save_machine(changed)

    with registry.connect() as conn:
        row = conn.execute(
            "SELECT report_year FROM machine_discoveries WHERE discovery_id=?",
            ("DPT_STABLE_CANDIDATE",),
        ).fetchone()
    assert row["report_year"] == "2024"


def test_machine_discovery_changed_machine_evidence_appends_revision(tmp_path: Path) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    discoveries = DiscoveryRegistry(registry)
    first = discoveries.save_machine(_candidate())

    changed = _candidate()
    changed["confidence"] = 0.91
    changed["candidate_note_pages"] = [48, 49]
    changed["evidence"] = {
        **changed["evidence"],
        "candidate_pages": [{"page": 48, "score": 0.91}],
    }
    revised = discoveries.save_machine(changed)
    replay = discoveries.save_machine(changed)

    assert revised["discovery_id"] != first["discovery_id"]
    assert "__R" in revised["discovery_id"]
    assert replay["discovery_id"] == revised["discovery_id"]
    assert replay["created_at"] == revised["created_at"]
    assert revised["machine_evidence_revision"]
    with registry.connect() as conn:
        rows = conn.execute(
            "SELECT discovery_id, confidence, candidate_note_pages_json FROM machine_discoveries "
            "ORDER BY created_at, discovery_id"
        ).fetchall()
    assert len(rows) == 2
    assert rows[0]["discovery_id"] == first["discovery_id"]
    assert rows[0]["confidence"] == 0.97
    assert rows[1]["discovery_id"] == revised["discovery_id"]
    assert rows[1]["confidence"] == 0.91


def test_per_pdf_discovery_failure_is_not_silently_dropped() -> None:
    rows = _guided_discovery_failure_rows(
        Path("中国太保2023年报.pdf"),
        {"company": "中国太保", "year": "2023"},
        {
            "failures": [{
                "family_id": "investment_portfolio",
                "failure_reason": "NO_DIRECT_PORTFOLIO_TABLE",
                "portfolio_topology_audit": {
                    "strategy": "DIRECT_PORTFOLIO_TABLES",
                    "native_pages_scanned": 250,
                    "ocr_used": False,
                },
            }],
        },
    )

    assert rows == [{
        "source_pdf": "中国太保2023年报.pdf",
        "company": "中国太保",
        "report_year": "2023",
        "family_id": "investment_portfolio",
        "failure_reason": "NO_DIRECT_PORTFOLIO_TABLE",
        "strategy": "DIRECT_PORTFOLIO_TABLES",
        "native_pages_scanned": 250,
        "ocr_used": False,
    }]


def test_append_only_occurrence_restores_equivalent_formal_anchor_decision(tmp_path: Path) -> None:
    registry = MetadataRegistry(tmp_path / "metadata.db")
    discoveries = DiscoveryRegistry(registry)
    physical_identity = {
        "pdf_id": r"C:\reports\新华保险2025年报.pdf",
        "company": "新华保险",
        "report_year": "2025",
        "statement_type": "BALANCE_SHEET",
        "scope": "CONSOLIDATED",
        "display_name": "金融投资",
        "table_family": "financial_investment",
        "source_table_title": "合并资产负债表",
        "statement_pdf_page_index": 146,
        "child_rows": [],
    }
    old = discoveries.save_occurrence({
        **physical_identity, "occurrence_id": "OCC_CERTIFIED_OLD",
    })
    discoveries.adjudicate_anchor(
        old["occurrence_id"], label="ACCEPTED", chosen_scope="CONSOLIDATED",
    )
    fresh = discoveries.save_occurrence({
        **physical_identity, "occurrence_id": "OCC_FRESH_APPEND_ONLY",
    })

    assert discoveries.is_anchor_certified(fresh["occurrence_id"]) is False
    assert discoveries.is_equivalent_anchor_certified(fresh) is True
    assert discoveries.is_equivalent_anchor_certified({
        **fresh, "statement_pdf_page_index": 147,
    }) is False
