#!/usr/bin/env python3
"""Targeted v6.6 validation: Ping An 2023 notes 9-12 only (not a regression suite)."""
from __future__ import annotations

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


def plan() -> dict:
    raw = extract_statement_anchor(PDF)
    assert raw["status"] == "FOUND", raw
    resolver = NoteReferenceResolver()
    children = []
    for child in raw["children"]:
        candidates = resolver.candidates_from_pdf(PDF, note_reference=child["note_reference_normalized"], member_table=child["member_table"])
        assert candidates, child
        children.append(dict(child) | {"certified_note_target": resolver.certify(candidates[0])})
    occ = StatementOccurrence(
        occurrence_id="PINGAN_2023_CONTEXT_VALIDATION", display_name="金融投资",
        statement_type=raw["statement_type"], source_table_title=raw["source_table_title"], scope=raw["scope"],
        statement_pdf_page_index=raw["statement_pdf_page_index"], statement_printed_page=raw["statement_printed_page"],
        parent_text=raw["parent_text"], child_rows=tuple(children), evidence={"targeted_validation": True},
    )
    out = build_capture_plan(occ, selected_anchor=True)
    out["plan_id"] = "PINGAN_2023_CONTEXT_VALIDATION"
    out["pdf_id"] = str(PDF)
    return out


def main() -> None:
    assert PDF.exists(), PDF
    with tempfile.TemporaryDirectory(prefix="v66_pingan_context_") as tmp:
        paths = ensure_data_home(Path(tmp), ROOT / "metric_aliases.json")
        backend = build_backend_services(paths)
        capture_plan = plan()
        backend.discovery_registry.save_capture_plan(capture_plan)
        batch = backend.research_batch_service.create("中国平安2023上下文与观察值验证", "金融投资")
        run = backend.guided_capture_service.execute(capture_plan, pdf_path=PDF, research_batch_id=batch["research_batch_id"], max_workers=2)
        deadline = time.time() + 120
        while time.time() < deadline:
            status = backend.table_capture_runner.monitor(run["batch_id"])
            if not status["is_running"]:
                break
            time.sleep(0.4)
        assert not status["is_running"], status
        assert not [j for j in status["jobs"] if j["status"] == "FAILED"], status
        ids = backend.research_batch_service.capture_ids(batch["research_batch_id"])
        assert len(ids) == 4, ids
        records = backend.merge_service.capture_repo.get_many(ids)
        native_values = []
        context_pages = []
        for record in records:
            raw = pd.read_csv(Path(record["run_path"]) / "table_raw_long.csv")
            amounts = raw[raw["value"].notna()]
            assert set(amounts["unit"].dropna().astype(str)) == {"百万元"}, amounts[["unit", "value"]].head().to_dict("records")
            assert set(amounts["currency_unit"].dropna().astype(str)) == {"CNY_MILLION"}
            assert set(amounts["report_year"].dropna().astype(str)) == {"2023"}
            # CSV round-tripping may materialise the two year columns as
            # 2023.0/2022.0.  Validate the semantic year rather than pandas'
            # incidental float rendering.
            observed_years = {str(int(float(value))) for value in amounts["data_year"].dropna()}
            assert observed_years >= {"2023", "2022"}, observed_years
            assert amounts["context_source_page"].notna().all()
            native_values.extend(amounts["value"].tolist())
            context_pages.extend(amounts["context_source_page"].tolist())
        # This guards the reported 1,733,996 -> 1,733,996,000,000 error:
        # native observations stay in the declared CNY_MILLION representation.
        assert any(abs(float(v) - 1733996.0) < 1e-9 for v in native_values), native_values[:20]
        merge = backend.merge_service.create(capture_ids=ids, table_id="金融投资")
        resolved = pd.read_csv(merge["artifacts"]["resolved_long"], encoding="utf-8-sig")
        wide = pd.read_csv(merge["artifacts"]["canonical_wide"], encoding="utf-8-sig")
        assert {"report_year", "data_year", "period_type", "currency_unit", "restated_flag", "statement_scope", "source_provenance"}.issubset(resolved.columns)
        assert resolved["source_provenance"].notna().all()
        value_columns = [c for c in wide.columns if c.startswith("company=")]
        assert value_columns and all("report_year=" in c and "data_year=" in c for c in value_columns), value_columns
        assert not any("data_year=2022.0" in c or "data_year=2023.0" in c for c in value_columns), value_columns
        assert not any(c == "2023" or c == "2022" or c.startswith("中国平安 | 2023 | 2022") for c in wide.columns), wide.columns.tolist()
        print("PINGAN_2023_NOTES_9_12_CONTEXT_UNIT_PASS", sorted(set(context_pages)))
        print("PINGAN_2023_CANONICAL_OBSERVATION_SCHEMA_PASS", len(resolved), len(wide), value_columns)


if __name__ == "__main__":
    main()
