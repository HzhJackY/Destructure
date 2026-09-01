"""Regression: strict Stage B links are children of one family Capture Plan."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from discovery_registry import DiscoveryRegistry
from metadata_registry import MetadataRegistry
from services.child_capture_execution_service import ChildCaptureExecutionService


class _TargetRepo:
    def certified_target(self, certified_link_id: str) -> dict:
        number = int(certified_link_id.rsplit("_", 1)[-1])
        return {
            "source_pdf_id": "PINGAN_2023",
            "member_table_id": f"member_{number}",
            "note_reference": f"附注八-{number}",
            "confirmed_note_pdf_page_index": 210 + number,
            "candidate_note_pdf_page_index": 210 + number,
            "statement_scope": "CONSOLIDATED",
            "target_heading": f"明细表{number}",
            "capture_query_title": f"明细表{number}",
        }


class _Discovery:
    def __init__(self):
        self.repo = _TargetRepo()


class _MixedTargetRepo(_TargetRepo):
    def certified_target(self, certified_link_id: str) -> dict:
        target = super().certified_target(certified_link_id)
        if certified_link_id == "CLINK_1":
            target["table_classification"] = "PRIMARY_TABLE"
        elif certified_link_id == "CLINK_2":
            target["table_classification"] = "SUPPLEMENTARY_TABLE"
        return target


class _MixedDiscovery:
    def __init__(self):
        self.repo = _MixedTargetRepo()


def _service(tmp_path: Path, discovery=None):
    registry = MetadataRegistry(tmp_path / "metadata.db")
    service = ChildCaptureExecutionService(
        registry=registry,
        capture_service=None,
        table_capture_runner=None,
        research_batch_service=None,
        guided_capture_service=None,
        hierarchical_child_discovery_service=discovery or _Discovery(),
    )
    return registry, service


def _link(number: int, *, anchor: str = "OCC_PINGAN_2023") -> dict:
    return {
        "certification_status": "CERTIFIED",
        "certified_link_id": f"CLINK_{number}",
        "anchor_id": anchor,
        "table_family_id": "金融投资",
        "member_table_id": f"member_{number}",
        "statement_scope": "CONSOLIDATED",
        "research_definition_id": "FINANCIAL_INVESTMENT_V1",
        "definition_version": "1",
        "pdf_id": "PINGAN_2023",
        "pdf_path": "C:/fixtures/pingan_2023.pdf",
        "company": "中国平安",
        "report_year": "2023",
        "member_table_order": number,
    }


def test_certified_siblings_collapse_to_one_statement_anchored_family_plan(tmp_path: Path):
    registry, service = _service(tmp_path)
    DiscoveryRegistry(registry).save_occurrence({
        "occurrence_id": "OCC_PINGAN_2023",
        "pdf_id": "PINGAN_2023",
        "company": "中国平安",
        "normalized_company": "中国平安",
        "report_year": "2023",
        "statement_type": "BALANCE_SHEET",
        "scope": "CONSOLIDATED",
        "display_name": "金融投资",
        "source_table_title": "合并资产负债表",
        "statement_pdf_page_index": 145,
        "statement_printed_page": "139",
        "parent_text": "金融投资",
        "child_rows": [{"member_table": f"member_{i}"} for i in range(9, 13)],
        "evidence": {"source": "fixture"},
    })

    plans = service._strict_links_to_plans(
        [_link(9), _link(10), _link(11), _link(12)],
        source_pdf_map={"PINGAN_2023": Path("C:/fixtures/pingan_2023.pdf")},
        research_definition={"definition_id": "FINANCIAL_INVESTMENT_V1", "definition_version": "1"},
        scope="CONSOLIDATED",
    )

    assert len(plans) == 1
    plan = plans[0]
    assert plan["company"] == "中国平安"
    assert plan["report_year"] == "2023"
    assert plan["source_pdf_id"] == "PINGAN_2023"
    assert plan["anchor_occurrence_id"] == "OCC_PINGAN_2023"
    assert plan["anchor"]["source_table_title"] == "合并资产负债表"
    assert plan["anchor"]["statement_pdf_page_index"] == 145
    assert plan["anchor"]["scope"] == "CONSOLIDATED"
    assert len(plan["items"]) == 5
    assert plan["items"][0]["member_table_role"] == "STATEMENT_ANCHOR"
    details = [item for item in plan["items"] if item["member_table_role"] == "NOTE_DETAIL"]
    assert [item["member_table"] for item in details] == [
        "member_9", "member_10", "member_11", "member_12",
    ]
    assert [item["confirmed_note_pdf_page_index"] for item in details] == [219, 220, 221, 222]
    persisted = DiscoveryRegistry(registry).save_capture_plan(plan)
    with registry.connect() as conn:
        plan_count = conn.execute("SELECT COUNT(*) AS n FROM capture_plans").fetchone()["n"]
        item_count = conn.execute(
            "SELECT COUNT(*) AS n FROM capture_plan_items WHERE plan_id=?",
            (persisted["plan_id"],),
        ).fetchone()["n"]
    assert plan_count == 1
    assert item_count == 5


def test_different_anchor_never_merges_into_existing_family_plan(tmp_path: Path):
    registry, service = _service(tmp_path)
    plans = service._strict_links_to_plans(
        [_link(9), _link(10, anchor="OCC_OTHER_SCOPE")],
        source_pdf_map={"PINGAN_2023": Path("C:/fixtures/pingan_2023.pdf")},
        research_definition={"definition_id": "FINANCIAL_INVESTMENT_V1", "definition_version": "1"},
        scope="CONSOLIDATED",
    )
    assert len(plans) == 2
    assert {plan["anchor_occurrence_id"] for plan in plans} == {
        "OCC_PINGAN_2023", "OCC_OTHER_SCOPE",
    }


def test_strict_plan_orders_primary_before_supplementary(tmp_path: Path):
    _, service = _service(tmp_path, _MixedDiscovery())
    links = [_link(2), _link(1)]
    links[0]["member_table_order"] = 1
    links[1]["member_table_order"] = 99

    plans = service._strict_links_to_plans(
        links,
        source_pdf_map={"PINGAN_2023": Path("C:/fixtures/pingan_2023.pdf")},
        research_definition={
            "definition_id": "FINANCIAL_INVESTMENT_V1",
            "definition_version": "1",
        },
        scope="CONSOLIDATED",
    )

    details = [
        item for item in plans[0]["items"]
        if item["member_table_role"] == "NOTE_DETAIL"
    ]
    assert [item["member_table"] for item in details] == [
        "member_1", "member_2",
    ]
