#!/usr/bin/env python3
"""Real 中国平安 2023 source-aware financial-investment merge acceptance."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend_context import build_backend_services  # noqa: E402
from data_home import ensure_data_home  # noqa: E402
from note_target_resolver import NoteReferenceResolver  # noqa: E402
from pdf_evidence import extract_statement_anchor  # noqa: E402
from statement_anchored_family import StatementOccurrence, build_capture_plan  # noqa: E402

PDF = Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf")


def make_plan() -> dict:
    raw = extract_statement_anchor(PDF)
    assert raw["status"] == "FOUND", raw
    resolver = NoteReferenceResolver()
    children = []
    for child in raw["children"]:
        candidates = resolver.candidates_from_pdf(
            PDF,
            note_reference=child["note_reference_normalized"],
            member_table=child["member_table"],
        )
        assert candidates, child
        children.append(dict(child) | {"certified_note_target": resolver.certify(candidates[0])})
    occurrence = StatementOccurrence(
        occurrence_id="REAL_PINGAN_2023_SOURCE_AWARE",
        display_name="金融投资", statement_type=raw["statement_type"],
        source_table_title=raw["source_table_title"], scope=raw["scope"],
        statement_pdf_page_index=raw["statement_pdf_page_index"],
        statement_printed_page=raw["statement_printed_page"], parent_text=raw["parent_text"],
        child_rows=tuple(children), evidence={"real_pdf": str(PDF)},
    )
    plan = build_capture_plan(occurrence, selected_anchor=True)
    plan["plan_id"] = "REAL_PINGAN_2023_SOURCE_AWARE"
    plan["pdf_id"] = str(PDF)
    assert plan["plan_status"] == "CERTIFIED", plan
    return plan


def member_count(frame: pd.DataFrame, terms: tuple[str, ...]) -> tuple[int, list[str]]:
    text = frame.get("canonical_item", pd.Series("", index=frame.index)).astype(str)
    # The source parser may preserve a parent label in the visible item, e.g.
    # “债券政府债”; match source labels without normalizing them into a single
    # cross-member canonical row.
    rows = frame[text.apply(lambda value: any(term in value for term in terms))].copy()
    return int(rows["member_table"].nunique()), sorted(rows["member_table"].dropna().astype(str).unique().tolist())


def main() -> None:
    assert PDF.exists(), PDF
    with tempfile.TemporaryDirectory(prefix="v66_pingan_source_aware_") as temp:
        paths = ensure_data_home(Path(temp), ROOT / "metric_aliases.json")
        backend = build_backend_services(paths)
        plan = make_plan()
        backend.discovery_registry.save_capture_plan(plan)
        batch = backend.research_batch_service.create("中国平安2023来源身份合表验收", "金融投资")
        execution = backend.guided_capture_service.execute(
            plan, pdf_path=PDF, research_batch_id=batch["research_batch_id"], max_workers=2
        )
        deadline = time.time() + 180
        summary = {}
        while time.time() < deadline:
            summary = backend.table_capture_runner.monitor(execution["batch_id"])
            if not summary["is_running"]:
                break
            time.sleep(0.5)
        assert summary and not summary["is_running"], summary
        statuses = [x["status"] for x in summary["jobs"]]
        assert len(statuses) == 4 and not any(x == "FAILED" for x in statuses), statuses
        capture_ids = backend.research_batch_service.capture_ids(batch["research_batch_id"])
        assert len(capture_ids) == 4, capture_ids
        merge = backend.merge_service.create(capture_ids=capture_ids, table_id="金融投资")
        artifacts = merge["artifacts"]
        resolved = pd.read_csv(artifacts["resolved_long"], encoding="utf-8-sig")
        conflicts = pd.read_csv(artifacts["conflicts"], encoding="utf-8-sig")
        wide = pd.read_csv(artifacts["canonical_wide"], encoding="utf-8-sig")
        identity_qa = pd.read_csv(artifacts["source_identity_qa"], encoding="utf-8-sig")
        assert set(identity_qa["member_table"].dropna()) >= {
            "以公允价值计量且其变动计入当期损益的金融资产", "债权投资", "其他债权投资"
        }, identity_qa.to_dict("records")
        value_conflicts = conflicts[conflicts.get("conflict_status", pd.Series(dtype=str)).eq("VALUE_CONFLICT")]
        assert value_conflicts.empty, value_conflicts.to_dict("records")
        assert {"table_family", "member_table", "row_path"}.issubset(wide.columns), wide.columns.tolist()
        # Reproduce the legacy, incorrect identity only for audit reporting:
        # it ignores member_table and shows how many false conflicts the old
        # row-key contract would have attempted to compare.
        legacy_dims = [
            "table_family", "row_path", "company", "document_year", "year",
            "scope", "restated", "period_type", "currency", "unit",
        ]
        legacy_groups = resolved.groupby(legacy_dims, dropna=False)["final_value"].nunique()
        legacy_false_conflicts = int((legacy_groups > 1).sum())
        result = {
            "capture_count": len(capture_ids),
            "member_table_count": int(resolved["member_table"].nunique()),
            "row_identity_count": int(len(resolved)),
            "simulated_pre_hotfix_false_value_conflict_count": legacy_false_conflicts,
            "value_conflict_count": int(len(value_conflicts)),
        }
        for label, terms, marker in [
            ("政府债", ("政府债", "政府债券"), "REAL_PINGAN_2023_GOV_BOND_MULTI_MEMBER_PASS"),
            ("金融债", ("金融债", "金融债券"), "REAL_PINGAN_2023_FINANCIAL_BOND_MULTI_MEMBER_PASS"),
            ("合计", ("合计", "总计", "小计", "净额", "总额"), "REAL_PINGAN_2023_TOTAL_MULTI_MEMBER_PASS"),
        ]:
            count, members = member_count(resolved, terms)
            result[label] = {"member_count": count, "members": members}
            # Source labels vary by table (some use 净额 rather than 合计); the
            # acceptance requirement is multiple preserved member rows, not a
            # forced display-string rewrite.
            assert count >= 3, (label, result[label], resolved[["member_table", "canonical_item"]].to_dict("records"))
            print(marker, json.dumps(result[label], ensure_ascii=False))
        print("REAL_PINGAN_2023_SOURCE_AWARE_MEMBER_MERGE_PASS", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
