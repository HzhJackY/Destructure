#!/usr/bin/env python3
"""Isolated v6.12 native-first / conditional-OCR real-PDF Canary.

The runner never uses the configured production DATA_HOME.  It creates a
throw-away Registry and Fast Index cache under an explicitly supplied runtime
directory, executes only FINANCIAL_INVESTMENT_V1, and writes compact audit
artifacts to the supplied output directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch


RELEASE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = RELEASE_ROOT.parents[1]
if str(RELEASE_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_ROOT))

import fast_index  # noqa: E402
from document_index_profile import fast_index_profile_kwargs  # noqa: E402
from generic_discovery_engine import GenericDiscoveryService  # noqa: E402
from metadata_registry import MetadataRegistry  # noqa: E402
from research_definition_registry import ResearchDefinitionService  # noqa: E402
from version import APP_VERSION  # noqa: E402


CASES = (
    {
        "case_id": "china_life_2025",
        "company": "中国人寿",
        "report_year": "2025",
        "pdf_name": "中国人寿2025年年度报告.pdf",
        "expected_sha256": "575a833fd7b83ad3568483273645236eddb751a92ab89f7e1c09105d92cedb27",
        "expected_total_pages": 228,
        "expected_anchor": 89,
        "requires_ocr": False,
    },
    {
        "case_id": "cpic_2025",
        "company": "中国太保",
        "report_year": "2025",
        "pdf_name": "中国太保2025年报.pdf",
        "expected_sha256": "0cf458e4f3705b6ce1453cf88a12ecf48454089e920aed451603a06f24db6803",
        "expected_total_pages": 279,
        "expected_anchor": 74,
        "requires_ocr": True,
    },
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _best_resolution(result: dict[str, Any]) -> dict[str, Any] | None:
    resolutions = [
        row for row in result.get("family_resolutions", [])
        if row.get("family_id") == "financial_investment"
    ]
    return max(
        resolutions,
        key=lambda row: (
            row.get("quality_status") == "RESOLVED",
            float(row.get("coverage_ratio") or 0),
        ),
        default=None,
    )


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    audits = [
        row for row in result.get("discovery_audits", [])
        if row.get("family_id") == "financial_investment"
    ]
    resolutions = [
        row for row in result.get("family_resolutions", [])
        if row.get("family_id") == "financial_investment"
    ]
    best = _best_resolution(result)
    audit = audits[0] if audits else {}
    ocr_candidates = [
        row for row in result.get("candidates", [])
        if row.get("ocr_used")
    ]
    ocr_amount_injection_count = sum(
        1
        for row in ocr_candidates
        if (
            row.get("amount_source_present")
            or row.get("statement_amount_raw")
            or row.get("statement_amount_normalized")
            or row.get("statement_amounts")
            or row.get("values")
        )
    )
    return {
        "anchors_one_based": sorted({
            int(row["statement_pdf_page_index"])
            for row in resolutions
            if row.get("statement_pdf_page_index") is not None
        }),
        "quality_status": best.get("quality_status") if best else None,
        "coverage_numerator": best.get("coverage_numerator") if best else None,
        "coverage_denominator": best.get("coverage_denominator") if best else None,
        "coverage_ratio": best.get("coverage_ratio") if best else None,
        "required_current_members": list(best.get("required_current_members") or []) if best else [],
        "missing_required_members": list(best.get("missing_required_members") or []) if best else [],
        "producer_version": best.get("producer_version") if best else None,
        "statement_index_source": audit.get("statement_index_source"),
        "statement_index_ocr_page_count": audit.get("statement_index_ocr_page_count"),
        "statement_index_cache_hit": audit.get("statement_index_cache_hit"),
        "native_index_reused": audit.get("native_index_reused"),
        "ocr_triggered": audit.get("ocr_triggered"),
        "ocr_pages": list(audit.get("ocr_pages") or []),
        "ocr_page_count": audit.get("ocr_page_count"),
        "fast_index_cache_hit": audit.get("fast_index_cache_hit"),
        "ocr_cache_namespace": audit.get("ocr_cache_namespace"),
        "ocr_cache_hits": audit.get("ocr_cache_hits"),
        "ocr_cache_misses": audit.get("ocr_cache_misses"),
        "final_status": audit.get("final_status"),
        "failure_reasons": [
            str(row.get("failure_reason") or "")
            for row in result.get("failures", [])
        ],
        "ocr_candidate_count": len(ocr_candidates),
        "ocr_amount_injection_count": ocr_amount_injection_count,
    }


def _evaluate(case: dict[str, Any], cold: dict[str, Any], warm: dict[str, Any],
              cold_calls: list[dict[str, Any]], warm_calls: list[dict[str, Any]],
              probe: dict[str, Any] | None) -> list[dict[str, Any]]:
    expected_anchor = int(case["expected_anchor"])
    checks = [
        ("native_index_source", cold.get("statement_index_source") == "FAST_INDEX_NATIVE_ONLY",
         cold.get("statement_index_source")),
        ("native_index_zero_ocr", cold.get("statement_index_ocr_page_count") == 0,
         cold.get("statement_index_ocr_page_count")),
        ("expected_anchor", expected_anchor in cold.get("anchors_one_based", []),
         cold.get("anchors_one_based")),
        ("required_coverage", cold.get("coverage_ratio") == 1.0,
         cold.get("coverage_ratio")),
        ("no_missing_required_members", not cold.get("missing_required_members"),
         cold.get("missing_required_members")),
        ("producer_version", cold.get("producer_version") == APP_VERSION,
         cold.get("producer_version")),
        ("ocr_amount_injection_zero", cold.get("ocr_amount_injection_count") == 0,
         cold.get("ocr_amount_injection_count")),
        ("warm_no_ocr_engine_call", not warm_calls, [x.get("page") for x in warm_calls]),
        ("warm_same_anchor", warm.get("anchors_one_based") == cold.get("anchors_one_based"),
         warm.get("anchors_one_based")),
        ("warm_same_coverage", warm.get("coverage_ratio") == cold.get("coverage_ratio"),
         warm.get("coverage_ratio")),
    ]
    if case["requires_ocr"]:
        selected = list(cold.get("ocr_pages") or [])
        checks.extend([
            ("conditional_ocr_triggered", cold.get("ocr_triggered") is True,
             cold.get("ocr_triggered")),
            ("anchor_in_selected_ocr_pages", expected_anchor in selected, selected),
            ("bounded_ocr_pages", 0 < len(selected) <= 12 and len(selected) < int(case["expected_total_pages"]),
             len(selected)),
            ("anchor_reached_real_ocr_engine", expected_anchor in [x.get("page") for x in cold_calls],
             [x.get("page") for x in cold_calls]),
            ("shared_page_cache_namespace",
             cold.get("ocr_cache_namespace") == "FAST_INDEX_SHARED_OCR_PAGE_CACHE",
             cold.get("ocr_cache_namespace")),
            ("cross_key_page_cache_reuse", bool(probe and probe.get("passed")), probe),
        ])
    else:
        checks.extend([
            ("native_path_did_not_trigger_conditional_ocr", cold.get("ocr_triggered") is False,
             cold.get("ocr_triggered")),
            ("native_path_no_ocr_engine_call", not cold_calls,
             [x.get("page") for x in cold_calls]),
        ])
    return [
        {"check": name, "status": "PASS" if passed else "FAIL", "observed": observed}
        for name, passed, observed in checks
    ]


def _run_service(service: GenericDiscoveryService, case: dict[str, Any], pdf_path: Path,
                 ocr_calls: list[dict[str, Any]], phase: str) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
    call_start = len(ocr_calls)
    started = time.perf_counter()
    result = service.discover(
        pdf_path=pdf_path,
        definition_id="FINANCIAL_INVESTMENT_V1",
        company=str(case["company"]),
        report_year=str(case["report_year"]),
        filing_type="ANNUAL_REPORT",
    )
    elapsed = round(time.perf_counter() - started, 3)
    phase_calls = [dict(row, phase=phase) for row in ocr_calls[call_start:]]
    return _summarize(result), phase_calls, elapsed


def _cross_key_probe(pdf_path: Path, cache_root: Path, selected: set[int],
                     ocr_calls: list[dict[str, Any]]) -> dict[str, Any]:
    if not selected:
        return {"passed": False, "reason": "NO_SELECTED_PAGES"}
    kwargs = fast_index_profile_kwargs(
        ocr_mode="selected",
        force_ocr_pages=selected,
    )
    kwargs["ocr_quality_threshold"] = float(kwargs["ocr_quality_threshold"]) + 0.001
    call_start = len(ocr_calls)
    started = time.perf_counter()
    _, meta = fast_index.build_fast_index(pdf_path, cache_root, **kwargs)
    elapsed = round(time.perf_counter() - started, 3)
    probe_calls = ocr_calls[call_start:]
    hits = int(meta.get("ocr_page_cache_hits") or 0)
    misses = int(meta.get("ocr_page_cache_misses") or 0)
    hit_pages = sorted(int(x) for x in (meta.get("ocr_page_cache_hit_pages") or []))
    return {
        "passed": (
            not meta.get("cache_hit")
            and hits == len(selected)
            and misses == 0
            and hit_pages == sorted(selected)
            and not probe_calls
        ),
        "fast_index_cache_hit": bool(meta.get("cache_hit")),
        "selected_pages": sorted(selected),
        "page_cache_hits": hits,
        "page_cache_misses": misses,
        "page_cache_hit_pages": hit_pages,
        "ocr_engine_call_pages": [int(row["page"]) for row in probe_calls],
        "elapsed_seconds": elapsed,
    }


def _write_csv(path: Path, case_results: list[dict[str, Any]]) -> None:
    fields = [
        "case_id", "phase", "status", "elapsed_seconds", "anchor_pages",
        "coverage_ratio", "statement_index_source", "statement_index_ocr_page_count",
        "ocr_triggered", "ocr_pages", "ocr_engine_calls", "ocr_cache_hits",
        "ocr_cache_misses", "ocr_amount_injection_count", "final_status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for case in case_results:
            for phase in ("cold", "warm"):
                summary = case.get(phase, {})
                calls = case.get(f"{phase}_ocr_calls", [])
                writer.writerow({
                    "case_id": case["case_id"],
                    "phase": phase,
                    "status": case.get("status"),
                    "elapsed_seconds": case.get(f"{phase}_elapsed_seconds"),
                    "anchor_pages": json.dumps(summary.get("anchors_one_based", []), ensure_ascii=False),
                    "coverage_ratio": summary.get("coverage_ratio"),
                    "statement_index_source": summary.get("statement_index_source"),
                    "statement_index_ocr_page_count": summary.get("statement_index_ocr_page_count"),
                    "ocr_triggered": summary.get("ocr_triggered"),
                    "ocr_pages": json.dumps(summary.get("ocr_pages", []), ensure_ascii=False),
                    "ocr_engine_calls": json.dumps([row.get("page") for row in calls]),
                    "ocr_cache_hits": summary.get("ocr_cache_hits"),
                    "ocr_cache_misses": summary.get("ocr_cache_misses"),
                    "ocr_amount_injection_count": summary.get("ocr_amount_injection_count"),
                    "final_status": summary.get("final_status"),
                })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--document-dir", type=Path, default=WORKSPACE_ROOT / "docu")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    runtime_dir = args.runtime_dir.resolve()
    document_dir = args.document_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if runtime_dir.exists() and any(runtime_dir.iterdir()):
        raise RuntimeError(f"runtime-dir 必须为空或不存在：{runtime_dir}")
    runtime_dir.mkdir(parents=True, exist_ok=True)

    registry_dir = runtime_dir / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    registry = MetadataRegistry(registry_dir / "metadata.db")
    definitions = ResearchDefinitionService(registry)
    if definitions.definition("FINANCIAL_INVESTMENT_V1") is None:
        raise RuntimeError("FINANCIAL_INVESTMENT_V1 未播种")

    real_ocr = fast_index._ocr_words_with_fallback
    ocr_calls: list[dict[str, Any]] = []

    def counted_ocr(page: Any, language: str, dpi: int) -> list[tuple]:
        event = {
            "case_id": active_case["case_id"],
            "page": int(page.number) + 1,
            "language": language,
            "dpi": int(dpi),
        }
        started = time.perf_counter()
        try:
            words = real_ocr(page, language, dpi)
            event["status"] = "PASS"
            event["word_count"] = len(words)
            return words
        except Exception as exc:
            event["status"] = "ERROR"
            event["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            event["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            ocr_calls.append(event)

    case_results: list[dict[str, Any]] = []
    active_case: dict[str, Any] = {"case_id": "PRESTART"}
    with patch.object(fast_index, "_ocr_words_with_fallback", new=counted_ocr):
        for case in CASES:
            active_case = case
            pdf_path = document_dir / str(case["pdf_name"])
            case_result: dict[str, Any] = {
                "case_id": case["case_id"],
                "company": case["company"],
                "report_year": case["report_year"],
                "pdf_path": str(pdf_path),
                "expected_sha256": case["expected_sha256"],
                "expected_anchor": case["expected_anchor"],
                "requires_ocr": case["requires_ocr"],
            }
            try:
                if not pdf_path.is_file():
                    raise FileNotFoundError(pdf_path)
                actual_sha = _sha256(pdf_path)
                case_result["actual_sha256"] = actual_sha
                case_result["sha256_status"] = "PASS" if actual_sha == case["expected_sha256"] else "FAIL"
                if actual_sha != case["expected_sha256"]:
                    raise RuntimeError("PDF_SHA256_MISMATCH")

                cache_root = runtime_dir / "cache" / str(case["case_id"])
                service = GenericDiscoveryService(definitions, cache_root=cache_root)
                cold, cold_calls, cold_elapsed = _run_service(
                    service, case, pdf_path, ocr_calls, "cold"
                )
                warm, warm_calls, warm_elapsed = _run_service(
                    service, case, pdf_path, ocr_calls, "warm"
                )
                probe = None
                if case["requires_ocr"]:
                    probe = _cross_key_probe(
                        pdf_path, cache_root, set(cold.get("ocr_pages") or []), ocr_calls
                    )
                checks = _evaluate(case, cold, warm, cold_calls, warm_calls, probe)
                case_result.update({
                    "cold": cold,
                    "warm": warm,
                    "cold_ocr_calls": cold_calls,
                    "warm_ocr_calls": warm_calls,
                    "cold_elapsed_seconds": cold_elapsed,
                    "warm_elapsed_seconds": warm_elapsed,
                    "cross_key_probe": probe,
                    "checks": checks,
                    "status": "PASS" if all(row["status"] == "PASS" for row in checks) else "FAIL",
                })
            except Exception as exc:
                case_result["status"] = "ERROR"
                case_result["error"] = f"{type(exc).__name__}: {exc}"
            case_results.append(case_result)
            print(
                f"{case_result['case_id']}: {case_result['status']} "
                f"cold={case_result.get('cold_elapsed_seconds')}s "
                f"warm={case_result.get('warm_elapsed_seconds')}s"
            )

    overall_status = "PASS" if case_results and all(
        row.get("status") == "PASS" for row in case_results
    ) else "FAIL"
    payload = {
        "release_version": APP_VERSION,
        "definition_id": "FINANCIAL_INVESTMENT_V1",
        "runtime_dir": str(runtime_dir),
        "production_data_home_used": False,
        "overall_status": overall_status,
        "cases": case_results,
    }
    (output_dir / "native_first_ocr_canary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "ocr_event_audit.json").write_text(
        json.dumps(ocr_calls, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(output_dir / "native_first_ocr_canary.csv", case_results)
    print(f"OVERALL_STATUS={overall_status}")
    return 0 if overall_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
