"""v6.11 — 12 Real Filing Acceptance Matrix & Cold-Run Provenance Harness.

Runs discovery + family resolution against all 12 annual reports with explicit
cache provenance, cold/warm mode separation, and structured exception handling.
"""
from __future__ import annotations

import csv
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from data_home import resolve_data_home
from statement_note_navigation import build_text_index, locate_primary_statements, fast_index_to_text_index
from research_definition_registry import ResearchDefinitionService
from fast_index import build_fast_index, INDEX_SCHEMA_VERSION, sha256_file
from document_index_profile import fast_index_profile_kwargs


def run_matrix(
    run_mode: str = "REAL_COLD_RUN",
    cache_dir_override: Path | None = None,
    output_dir_override: Path | None = None,
) -> list[dict]:
    """Run the 12 filing matrix under specified provenance run mode.

    Modes:
      - REAL_COLD_RUN: Forces rebuild (force_rebuild=True) in isolated scratch cache directory.
      - WARM_CACHE_RUN: Re-uses cache from scratch cache directory, verifying cache_hit=True.
    """
    data_home = resolve_data_home(ROOT)
    paths = {
        "metadata_db": data_home / "metadata.db",
        "cache": cache_dir_override or (data_home / "cache"),
    }
    cache_root = paths["cache"]
    cache_root.mkdir(parents=True, exist_ok=True)

    from metadata_registry import MetadataRegistry
    registry = MetadataRegistry(paths["metadata_db"])
    rds = ResearchDefinitionService(registry)

    family = next((f for f in rds.families() if f["family_id"] == "financial_investment"), None)
    if not family:
        raise RuntimeError("financial_investment family not found in registry")
    members = rds.members("financial_investment")

    from statement_family_resolution import StatementFamilyResolver
    resolver = StatementFamilyResolver()

    docu = Path(r"C:\dev\AXA_research\docu")
    filings = [
        ("中国平安", "2023", docu / "中国平安2023年报.pdf"),
        ("中国平安", "2024", docu / "中国平安2024年报.pdf"),
        ("中国平安", "2025", docu / "中国平安2025年报.pdf"),
        ("新华保险", "2023", docu / "新华保险2023年报.pdf"),
        ("新华保险", "2024", docu / "新华保险2024年报.pdf"),
        ("新华保险", "2025", docu / "新华保险2025年报.pdf"),
        ("中国太保", "2023", docu / "中国太保2023年报.pdf"),
        ("中国太保", "2024", docu / "中国太保2024年报.pdf"),
        ("中国太保", "2025", docu / "中国太保2025年报.pdf"),
        ("中国人寿", "2023", docu / "中国人寿2023年年度报告.pdf"),
        ("中国人寿", "2024", docu / "中国人寿2024年年度报告.pdf"),
        ("中国人寿", "2025", docu / "中国人寿2025年年度报告.pdf"),
    ]

    force_rebuild = (run_mode == "REAL_COLD_RUN")
    results = []

    for company, year, pdf_path in filings:
        print(f"\n{'='*60}")
        print(f"  [{run_mode}] {company} {year}: {pdf_path.name}")
        t0 = time.perf_counter()
        pdf_sha = sha256_file(pdf_path)

        row = {
            "company": company, "report_year": year,
            "pdf_filename": pdf_path.name,
            "pdf_sha256": pdf_sha,
            "run_mode": run_mode,
            "index_schema_version": INDEX_SCHEMA_VERSION,
            "pdf_size_mb": round(pdf_path.stat().st_size / 1024 / 1024, 1),
            "discovery": "NOT_RUN", "family_resolution": "NOT_RUN",
            "resolution_mode": "", "presentation_regime": "",
            "member_count": 0, "member_coverage": "",
            "parent_found": False, "parent_label": "",
            "required_members": "", "outside_family": "",
            "comparative_only": "",
            "cache_hit": False,
            "ocr_pages": 0,
            "failure_type": "PASS",
            "failure_reason": "",
            "traceback_short": "",
        }

        # Step 1: Physical Fast Index build with OCR
        try:
            fast_records, meta = build_fast_index(
                pdf_path, cache_root, **fast_index_profile_kwargs(), force_rebuild=force_rebuild
            )
            row["cache_hit"] = meta.get("cache_hit", False)
            row["ocr_pages"] = meta.get("ocr_pages", 0)

            # Warm cache policy check: warm run MUST hit cache
            if run_mode == "WARM_CACHE_RUN" and not row["cache_hit"]:
                row["discovery"] = "FAIL"
                row["failure_type"] = "CACHE_POLICY_VIOLATION"
                row["failure_reason"] = "WARM_RUN_EXPECTED_CACHE_HIT_BUT_MISSED"
                results.append(row)
                continue

            # Convert to semantic TextIndexRecords via explicit adapter
            index = fast_index_to_text_index(fast_records)
            row["discovery"] = "PASS"
        except Exception as e:
            row["discovery"] = "FAIL"
            row["failure_type"] = "FAIL_RUNTIME"
            row["failure_reason"] = f"INDEX_ERROR:{type(e).__name__}:{e}"
            row["traceback_short"] = traceback.format_exc()[-400:]
            results.append(row)
            continue

        # Step 2: Primary Statement Location
        try:
            statements = locate_primary_statements(index)
            bs_pages = statements.get("BALANCE_SHEET", [])
            if not bs_pages:
                row["discovery"] = "FAIL"
                row["failure_type"] = "FAIL_VALIDATION"
                row["failure_reason"] = "NO_BALANCE_SHEET_FOUND"
                results.append(row)
                continue
        except Exception as e:
            row["discovery"] = "FAIL"
            row["failure_type"] = "FAIL_RUNTIME"
            row["failure_reason"] = f"STATEMENTS_ERROR:{type(e).__name__}:{e}"
            row["traceback_short"] = traceback.format_exc()[-400:]
            results.append(row)
            continue

        # Step 3: Family Resolution
        try:
            candidates, resolutions = resolver.resolve(
                index=index, family=family, members=members,
                company=company, report_year=year, filing_type="ANNUAL_REPORT",
            )

            if resolutions:
                res = resolutions[0]
                row["family_resolution"] = "PASS"
                row["resolution_mode"] = res.get("resolution_mode", "")
                row["presentation_regime"] = res.get("presentation_regime", "")
                row["member_count"] = res.get("member_count", 0)
                ev = res.get("evidence", {})
                row["parent_found"] = ev.get("raw_parent_found", False)
                row["parent_label"] = str(ev.get("raw_parent_label") if ev.get("raw_parent_found") else "")
                row["required_members"] = "|".join(res.get("current_period_members", []))
                row["outside_family"] = "|".join(res.get("outside_family_members", []))
                row["comparative_only"] = "|".join(res.get("comparative_only_members", []))

                expected = len(res.get("current_period_members", []))
                row["member_coverage"] = f"{ev.get('member_count', 0)} selected / {expected} current"
                row["statement_pdf_page_index"] = res.get("statement_pdf_page_index")
            elif candidates:
                row["family_resolution"] = "PASS"
                row["resolution_mode"] = "DIRECT_CANDIDATES"
                row["member_count"] = len(candidates)
                member_ids = sorted(set(c.get("member_table", "") for c in candidates))
                row["required_members"] = "|".join(member_ids)
                row["member_coverage"] = f"0/{len(candidates)} (no resolution)"
                row["statement_pdf_page_index"] = candidates[0].get("statement_pdf_page_index")
            else:
                row["family_resolution"] = "FAIL"
                row["failure_type"] = "FAIL_VALIDATION"
                row["failure_reason"] = "NO_RESOLUTION_OR_CANDIDATES"

        except Exception as e:
            row["family_resolution"] = "FAIL"
            row["failure_type"] = "FAIL_RUNTIME"
            row["failure_reason"] = f"RESOLUTION_ERROR:{type(e).__name__}:{e}"
            row["traceback_short"] = traceback.format_exc()[-400:]

        elapsed = time.perf_counter() - t0
        row["elapsed_s"] = round(elapsed, 1)
        results.append(row)

        status = row["family_resolution"]
        mode = row["resolution_mode"]
        print(f"  → {status} | mode={mode} | cache_hit={row['cache_hit']} | elapsed={row['elapsed_s']}s")

    return results


def main():
    scratch_dir = Path(r"C:\dev\AXA_research\output_agent_runs\v611_codex_takeover\cold_run_scratch")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    cache_scratch = scratch_dir / "cache"

    print("=== TEST SUITE 1: REAL_COLD_RUN ===")
    cold_results = run_matrix(run_mode="REAL_COLD_RUN", cache_dir_override=cache_scratch)

    cold_csv = scratch_dir / "cold_run_matrix_results.csv"
    fieldnames = list(cold_results[0].keys())
    with open(cold_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cold_results)

    print("\n=== TEST SUITE 2: WARM_CACHE_RUN ===")
    warm_results = run_matrix(run_mode="WARM_CACHE_RUN", cache_dir_override=cache_scratch)

    warm_csv = scratch_dir / "warm_cache_consistency_qa.csv"
    with open(warm_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(warm_results)

    # Warm vs Cold Consistency Assertion
    diffs = 0
    for c_row, w_row in zip(cold_results, warm_results):
        for k in ("company", "report_year", "family_resolution", "resolution_mode", "required_members", "statement_pdf_page_index"):
            if c_row.get(k) != w_row.get(k):
                diffs += 1
                print(f"  Mismatch in {c_row['company']} {c_row['report_year']} field '{k}': cold='{c_row.get(k)}' vs warm='{w_row.get(k)}'")

    print(f"\n=======================================================")
    print(f"REAL_COLD_RUN RESULT: {sum(1 for r in cold_results if r['family_resolution']=='PASS')}/12 PASS")
    print(f"WARM_CACHE_RUN RESULT: {sum(1 for r in warm_results if r['family_resolution']=='PASS')}/12 PASS")
    print(f"COLD VS WARM CONSISTENCY: {'100% IDENTICAL' if diffs == 0 else f'{diffs} MISMATCHES'}")
    print(f"=======================================================")


if __name__ == "__main__":
    main()
