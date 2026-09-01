from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


RELEASE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = RELEASE_ROOT.parents[1]
sys.path.insert(0, str(RELEASE_ROOT))

from registry_acceptance import (  # noqa: E402
    AcceptanceStage,
    AcceptanceStatus,
    FINANCIAL_PROFILE,
    PORTFOLIO_PROFILE,
    RegistryAcceptanceHarness,
    StageResult,
    financial_v6_shadow_stage_result,
)


def _csv_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "pass"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fail-closed dual Registry acceptance snapshot")
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, default=REPO_ROOT / "golden_corpus" / "v1.2.0")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--profile", choices=("both", "portfolio", "financial"), default="both",
    )
    parser.add_argument("--research-batch-id", action="append", default=[])
    parser.add_argument("--formal-merge-audit", type=Path)
    parser.add_argument("--financial-v6-shadow", type=Path)
    parser.add_argument("--ui-parity-matrix", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    shadow_results = {}
    for row in _csv_rows(args.financial_v6_shadow):
        normalized: dict[str, object] = dict(row)
        for field in (
            "v2_pass", "golden_identity_match", "required_current_member_status_valid",
            "physical_row_identity_unique", "note_value_binding_verified",
        ):
            normalized[field] = _bool(row.get(field))
        normalized["cross_row_binding_conflicts"] = int(row.get("cross_row_binding_conflicts") or 0)
        normalized["duplicate_active_member_occurrences"] = int(row.get("duplicate_active_member_occurrences") or 0)
        shadow_results[(str(row.get("company_id") or ""), int(row.get("report_year") or 0))] = (
            financial_v6_shadow_stage_result(normalized)
        )
    parity_results = {}
    for row in _csv_rows(args.ui_parity_matrix):
        status = AcceptanceStatus(str(row.get("status") or "NOT_RUN"))
        evidence = {
            "offline_count": int(row.get("offline_count") or 0),
            "ui_count": int(row.get("ui_count") or 0),
            "offline_sha256": row.get("offline_sha256"),
            "ui_sha256": row.get("ui_sha256"),
            "financial_v6_identity_fields_compared": _bool(
                row.get("financial_v6_identity_fields_compared")
            ),
            "browser_e2e": row.get("browser_e2e") or "SKIPPED_BY_USER",
        }
        parity_results[(
            FINANCIAL_PROFILE.definition_id,
            str(row.get("company_id") or ""), int(row.get("report_year") or 0),
        )] = StageResult(
            AcceptanceStage.UI_PARITY, status,
            str(row.get("reason_code") or "UI_PARITY_EVIDENCE_IMPORTED"), evidence,
        )
    merge_ids = [
        str(row.get("merge_id") or "")
        for row in _csv_rows(args.formal_merge_audit)
        if str(row.get("status") or "") == "PASS" and str(row.get("merge_id") or "")
    ]
    harness = RegistryAcceptanceHarness(
        corpus_root=args.corpus_root, metadata_db=args.metadata_db,
        research_batch_ids=args.research_batch_id,
        formal_merge_ids=merge_ids,
        financial_v6_evidence_results=shadow_results,
        ui_parity_results=parity_results,
    )
    results = []
    if args.profile in {"both", "portfolio"}:
        results.extend(harness.evaluate_profile(PORTFOLIO_PROFILE))
    if args.profile in {"both", "financial"}:
        results.extend(harness.evaluate_profile(FINANCIAL_PROFILE))
    payload = [result.to_dict() for result in results]
    (args.output_dir / "acceptance_matrix.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    fieldnames = [
        "definition_id", "family", "company_id", "company_name", "report_year",
        "pdf_sha256", "overall_status", "stage", "stage_status", "reason_code", "evidence_json",
    ]
    with (args.output_dir / "acceptance_matrix.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            for stage in result.stages:
                writer.writerow({
                    "definition_id": result.definition_id,
                    "family": result.family,
                    "company_id": result.company_id,
                    "company_name": result.company_name,
                    "report_year": result.report_year,
                    "pdf_sha256": result.pdf_sha256,
                    "overall_status": result.status.value,
                    "stage": stage.stage.value,
                    "stage_status": stage.status.value,
                    "reason_code": stage.reason_code,
                    "evidence_json": json.dumps(stage.evidence, ensure_ascii=False, sort_keys=True),
                })
    summary: dict[str, dict[str, int]] = {}
    for result in results:
        summary.setdefault(result.definition_id, {})
        summary[result.definition_id][result.status.value] = (
            summary[result.definition_id].get(result.status.value, 0) + 1
        )
    (args.output_dir / "acceptance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if results and all(result.status == AcceptanceStatus.PASS for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
