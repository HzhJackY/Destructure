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
    FINANCIAL_PROFILE,
    PORTFOLIO_PROFILE,
    RegistryAcceptanceHarness,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fail-closed dual Registry acceptance snapshot")
    parser.add_argument("--metadata-db", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, default=REPO_ROOT / "golden_corpus" / "v1.1.0")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    harness = RegistryAcceptanceHarness(corpus_root=args.corpus_root, metadata_db=args.metadata_db)
    results = harness.evaluate_profile(PORTFOLIO_PROFILE) + harness.evaluate_profile(FINANCIAL_PROFILE)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
