#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_home import ensure_data_home
from backend_context import build_backend_services

RUNTIME = PROJECT_ROOT / "_v61_regression_runtime"
shutil.rmtree(RUNTIME, ignore_errors=True)
RUNTIME.mkdir(parents=True)
paths = ensure_data_home(RUNTIME, PROJECT_ROOT / "metric_aliases.json")


def write_capture(run_id: str, *, batch_id: str, pdf_name: str, table_query: str = "业务及管理费") -> Path:
    d = paths["table_captures"] / run_id
    d.mkdir(parents=True, exist_ok=True)
    result = {
        "producer_version": "v6.1",
        "pdf_name": pdf_name,
        "pdf_sha256": "sha-" + run_id,
        "table_query": table_query,
        "note_number": "34",
        "start_page": 1,
        "end_page": 1,
        "pages": [1],
        "columns": [
            {"ordinal": 0, "source_column_index": 1, "header_raw": "2024", "year": "2024", "scope": "本集团", "restated": False, "period_label": "2024"},
            {"ordinal": 1, "source_column_index": 2, "header_raw": "2023", "year": "2023", "scope": "本集团", "restated": False, "period_label": "2023"},
        ],
        "rows": [],
        "warnings": [],
        "stats": {"header_parser": "ABSOLUTE_YEAR_CLASSIC", "boundary_reason": "next_note_35"},
        "boundary_status": "HARD_BOUNDARY_CONFIRMED",
        "header_dimension_status": "AUTO_CONFIRMED",
    }
    (d / "table_capture_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "run_id": run_id,
        "display_name": run_id,
        "source_pdf_display": pdf_name,
        "table_query": table_query,
        "batch_id": batch_id,
        "producer_version": "v6.1",
        "header_parser": "ABSOLUTE_YEAR_CLASSIC",
        "lifecycle_status": "ACTIVE",
        "created_at": "2026-07-22T10:00:00+08:00",
        "company": "测试保险",
        "document_year": "2023" if "2023" in pdf_name else "2024",
        "asset_schema_version": "6.1",
    }
    (d / "capture_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


# Source PDF index assets.
for name in ["测试保险2024.pdf", "测试保险2023.pdf"]:
    (paths["uploads"] / name).write_bytes(b"%PDF-1.4\n% v61-regression\n")

cap_a = write_capture("CAP_A", batch_id="BATCH_A", pdf_name="测试保险2024.pdf")
cap_b = write_capture("CAP_B", batch_id="BATCH_A", pdf_name="测试保险2023.pdf")

merge = paths["table_merges"] / "MERGE_A"
merge.mkdir(parents=True)
(merge / "merge_manifest.json").write_text(json.dumps({
    "version": "v6.1",
    "merge_schema_version": "6.1",
    "table_id": "TEST_TABLE",
    "sources": [{"capture_run_id": "CAP_A"}],
}, ensure_ascii=False, indent=2), encoding="utf-8")
(merge / "merge_metadata.json").write_text(json.dumps({
    "run_id": "MERGE_A",
    "display_name": "测试合表",
    "lifecycle_status": "ACTIVE",
    "dependency_status": "CURRENT",
    "stale_capture_run_ids": [],
    "created_at": "2026-07-22T10:10:00+08:00",
}, ensure_ascii=False, indent=2), encoding="utf-8")

backend = build_backend_services(paths)
boot = backend.registry_service.bootstrap_if_needed()
assert paths["metadata_db"].exists()
counts = backend.registry_service.stats()["counts"]
assert counts["captures"] == 2, counts
assert counts["merge_projects"] == 1, counts
assert counts["pdf_assets"] == 2, counts
print("SQLITE_REGISTRY_BOOTSTRAP_PASS")

# Headless architecture must not require Streamlit.
assert "streamlit" not in sys.modules
assert backend.capture_service.count(include_trash=False) == 2
print("HEADLESS_SERVICE_LAYER_PASS")

# SQL filter/pagination contract.
assert backend.capture_service.count(document_year="2024", include_trash=False) == 1
page = backend.capture_service.list(include_trash=False, limit=1, offset=0)
assert len(page) == 1
assert backend.capture_service.filter_options()["producer_version"] == ["v6.1"]
assert backend.asset_service.matching_capture_ids(document_year="2024", include_trash=False) == ["CAP_A"]
print("SQL_FILTER_PAGINATION_PASS")

# Batch main table excludes fully trashed batches; batch status is aggregated.
batches = backend.batch_service.list_batches(include_fully_trashed=False)
assert len(batches) == 1 and batches[0]["batch_id"] == "BATCH_A"
assert batches[0]["active_count"] == 2 and batches[0]["trashed_count"] == 0
print("BATCH_AGGREGATE_STATUS_PASS")

# Dependency index should avoid rescanning merge directories for impact query.
impact = backend.asset_service.dependency_impact(["CAP_A"])
assert impact["dependent_merge_count"] == 1
assert impact["dependent_merges"][0]["merge_run_id"] == "MERGE_A"
print("SQL_DEPENDENCY_INDEX_PASS")

# Invalidation updates legacy evidence metadata + registry and marks merge stale.
out = backend.asset_service.invalidate(["CAP_A"], reason_code="HEADER_TOPOLOGY_ERROR", note="regression")
assert out["invalidated"] == ["CAP_A"]
a = backend.capture_service.get("CAP_A")
assert a["lifecycle_status"] == "INVALIDATED"
m = backend.merge_service.list(include_trash=False)[0]
assert m["dependency_status"] == "STALE_SOURCE_INVALIDATED", m
print("SERVICE_INVALIDATE_DUAL_WRITE_PASS")

# Reactivation refreshes dependency to CURRENT.
backend.asset_service.reactivate(["CAP_A"])
assert backend.capture_service.get("CAP_A")["lifecycle_status"] == "ACTIVE"
assert backend.merge_service.list(include_trash=False)[0]["dependency_status"] == "CURRENT"
print("SERVICE_REACTIVATE_DEPENDENCY_PASS")

# Entire batch -> trash: disappears from main batches and appears in Batch Trash.
trash = backend.batch_service.trash(["BATCH_A"])
assert len(trash["trashed"]) == 2
main_batches = backend.batch_service.list_batches(include_fully_trashed=False)
assert not any(x["batch_id"] == "BATCH_A" for x in main_batches), main_batches
trash_batches = backend.batch_service.list_batches(include_fully_trashed=True, only_with_trash=True)
batch_a = [x for x in trash_batches if x["batch_id"] == "BATCH_A"][0]
assert batch_a["batch_status"] == "TRASHED" and batch_a["trashed_count"] == 2
print("BATCH_ACTIVE_TRASH_SEPARATION_PASS")

# Restore through service using registry paths.
trash_ids = backend.batch_service.trashed_capture_ids("BATCH_A")
assert set(trash_ids) == {"CAP_A", "CAP_B"}
rest = backend.asset_service.restore(trash_ids)
assert len(rest["restored"]) == 2
assert any(x["batch_id"] == "BATCH_A" for x in backend.batch_service.list_batches(include_fully_trashed=False))
print("SERVICE_TRASH_RESTORE_PASS")

# Persistent job registry foundation.
job = backend.job_service.create("TABLE_CAPTURE", batch_id="BATCH_JOB", source_asset_id="CAP_A", payload={"parser": "AUTO"})
assert job["status"] == "QUEUED"
job = backend.job_service.update(job["job_id"], status="RUNNING", progress=0.5)
assert job["status"] == "RUNNING" and abs(job["progress"] - 0.5) < 1e-9
job = backend.job_service.update(job["job_id"], status="SUCCESS", progress=1.0, result={"capture_id": "CAP_NEW"})
assert job["status"] == "SUCCESS" and job["result"]["capture_id"] == "CAP_NEW"
print("PERSISTENT_JOB_REGISTRY_PASS")

# Registry is rebuildable from filesystem: delete DB, rebuild, counts return.
for suffix in ["", "-wal", "-shm"]:
    p = Path(str(paths["metadata_db"]) + suffix)
    if p.exists():
        p.unlink()
backend2 = build_backend_services(paths)
out = backend2.registry_service.full_sync("REGRESSION_REBUILD")
assert out["captures"] == 2 and out["merges"] == 1 and out["pdf_assets"] == 2
assert backend2.registry_service.stats()["counts"]["captures"] == 2
print("REGISTRY_REBUILD_FROM_DATA_HOME_PASS")

# End-to-end headless Capture -> Review -> Merge through Service APIs.
import fitz
service_pdf = paths["uploads"] / "服务层测试2024.pdf"
doc = fitz.open(); page = doc.new_page(width=900, height=900)
page.insert_text((50, 60), "34. 业务及管理费", fontname="china-s", fontsize=14)
page.insert_text((560, 105), "本集团", fontname="china-s", fontsize=11)
xs = [520, 700]
for x, t in zip(xs, ["2024年度", "2023年度"]):
    page.insert_text((x, 140), t, fontname="china-s", fontsize=10)
y = 210
for n in range(6):
    page.insert_text((80, y), f"费用项目{n}", fontname="china-s", fontsize=10)
    page.insert_text((xs[0], y), str((100+n)*1000), fontsize=10)
    page.insert_text((xs[1], y), str((90+n)*1000), fontsize=10)
    y += 35
page.insert_text((50, 600), "35. 下一附注", fontname="china-s", fontsize=14)
doc.save(service_pdf); doc.close()
created = backend2.capture_service.create(
    pdf_path=service_pdf, table_query="业务及管理费", batch_id="HEADLESS_SERVICE_BATCH", header_parser_mode="AUTO"
)
service_capture_id = created["capture_id"]
service_capture = backend2.capture_service.get(service_capture_id)
assert service_capture is not None and service_capture["batch_id"] == "HEADLESS_SERVICE_BATCH"
assert service_capture.get("pdf_id"), service_capture
run_dir = Path(created["run_path"])
result_data = json.loads((run_dir / "table_capture_result.json").read_text(encoding="utf-8"))
edited_columns = [
    {"ordinal": c["ordinal"], "year": c["year"], "scope": c.get("scope") or "本集团", "restated": bool(c.get("restated"))}
    for c in result_data["columns"]
]
backend2.review_service.apply_header_dimensions(run_dir, edited_columns, "v6.1 headless regression")
merge_created = backend2.merge_service.create(
    capture_ids=[service_capture_id], table_id="HEADLESS_SERVICE_TABLE"
)
assert Path(merge_created["run_path"]).joinpath("merge_manifest.json").exists()
assert any(x["merge_id"] == merge_created["merge_id"] for x in backend2.merge_service.list())
print("HEADLESS_CAPTURE_REVIEW_MERGE_SERVICE_PASS")

# Project-root documentation cleanup contract.
root_markdown = sorted(x.name for x in PROJECT_ROOT.glob("*.md"))
assert root_markdown == ["CHANGELOG.md", "README.md"], root_markdown
assert (PROJECT_ROOT / "docs" / "history" / "v6.0.1" / "README_V6_0_1.md").exists()
assert (PROJECT_ROOT / "docs" / "current" / "ARCHITECTURE_V6_1.md").exists()
print("PROJECT_DOCUMENTATION_CLEANUP_PASS")

print("ALL_V61_BACKEND_ARCHITECTURE_TESTS_PASS")
shutil.rmtree(RUNTIME, ignore_errors=True)
