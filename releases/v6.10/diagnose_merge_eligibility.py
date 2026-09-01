"""Diagnostic: check why captures are not merge-eligible after v6.10 hotfix."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import json
from capture_library import (
    capture_readiness, derive_boundary_status, derive_boundary_decision,
    MERGE_READY_STATUSES,
)
from services.review_task_service import ReviewTaskService


def diagnose(paths: dict) -> None:
    from metadata_registry import MetadataRegistry
    registry = MetadataRegistry(paths["metadata_db"])

    with registry.connect() as conn:
        # All capture_versions with is_current=1
        current = conn.execute(
            """SELECT cv.*, c.run_path, c.pdf_name, c.table_query
               FROM capture_versions cv
               LEFT JOIN captures c ON c.capture_id = cv.capture_id
               WHERE cv.is_current = 1
               ORDER BY cv.updated_at DESC"""
        ).fetchall()

        if not current:
            print("NO CURRENT CAPTURE VERSIONS FOUND")
            return

        print(f"Found {len(current)} current capture versions\n")

        issues = conn.execute(
            "SELECT capture_version_id, reason_code, status, blocking, severity FROM review_issues WHERE status='OPEN'"
        ).fetchall()
        issue_by_capture: dict[str, list] = {}
        for iss in issues:
            d = dict(iss)
            issue_by_capture.setdefault(str(d["capture_version_id"]), []).append(d)

    for crow in current:
        row = dict(crow)
        capture_id = str(row["capture_id"])
        quality = str(row["quality_status"] or "")
        review = str(row["review_status"] or "")
        asset_status = str(row["asset_status"] or "")
        run_path = str(row["run_path"] or "")

        issues_list = issue_by_capture.get(capture_id, [])

        meets = {
            "is_current": bool(row["is_current"]),
            "registration_status": str(row["registration_status"] or "") == "REGISTERED",
            "quality_status_READY": quality == "READY",
            "review_status_CONFIRMED": review in {"CONFIRMED_AUTO", "CONFIRMED_HUMAN", "CONFIRMED_OVERRIDE"},
            "asset_status_CERTIFIED_ACTIVE": asset_status == "CERTIFIED_ACTIVE",
            "research_definition_id": bool(str(row.get("research_definition_id") or "").strip()),
            "definition_version": bool(str(row.get("definition_version") or "").strip()),
            "table_family_id": bool(str(row.get("table_family_id") or "").strip()),
            "statement_scope": str(row.get("statement_scope") or "UNKNOWN").upper() not in {"", "UNKNOWN", "NONE"},
        }
        all_ok = all(meets.values())
        failed = [k for k, v in meets.items() if not v]

        realtime = {}
        if run_path:
            result_path = Path(run_path) / "table_capture_result.json"
            if result_path.is_file():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    readiness = capture_readiness(result)
                    realtime = {
                        "boundary_status": readiness.get("boundary_status"),
                        "merge_ready": readiness.get("merge_ready"),
                        "capture_quality_status": readiness.get("capture_quality_status"),
                        "merge_blockers": readiness.get("merge_blockers"),
                        "unresolved_implicit_rows": readiness.get("unresolved_implicit_rows"),
                    }
                except Exception as e:
                    realtime = {"error": str(e)}

        print(f"CAPTURE {capture_id}:")
        print(f"  quality={quality} review={review} asset={asset_status}")
        print(f"  MERGE_ELIGIBLE: {all_ok}")
        if failed:
            print(f"  FAILED CHECKS: {failed}")
        if issues_list:
            print(f"  OPEN ISSUES ({len(issues_list)}):")
            for iss in issues_list:
                print(f"    - {iss['reason_code']} blocking={iss['blocking']} severity={iss['severity']}")
        if realtime:
            print(f"  REALTIME capture_readiness():")
            for k, v in realtime.items():
                print(f"    {k}: {v}")
        print()


if __name__ == "__main__":
    from data_home import resolve_data_home
    root = resolve_data_home(Path.cwd())
    paths = {"metadata_db": root / "metadata.db"}
    diagnose(paths)
