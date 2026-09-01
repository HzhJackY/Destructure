#!/usr/bin/env python3
from __future__ import annotations
import shutil, sys, time
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT))
from data_home import ensure_data_home
from backend_context import build_backend_services
from jobs.table_capture_runner import TableCaptureRunner
from services.table_family_service import INVESTMENT_RETURN_FAMILY

runtime=PROJECT_ROOT / "_v62_regression_runtime"; shutil.rmtree(runtime,ignore_errors=True); runtime.mkdir()
paths=ensure_data_home(runtime,PROJECT_ROOT / "metric_aliases.json")
backend=build_backend_services(paths)
legacy=paths["uploads"] / "legacy.pdf"; split=paths["uploads"] / "split.pdf"; flaky=paths["uploads"] / "flaky.pdf"
for path in [legacy,split,flaky]: path.write_bytes(b"%PDF-1.4\n")
attempts={}
def fake_capture(**kwargs):
    pdf=Path(kwargs["pdf_path"]).name; table=kwargs["table_query"]; key=(pdf,table); attempts[key]=attempts.get(key,0)+1
    if pdf=="legacy.pdf" and table!="投资净收益": raise RuntimeError("table not found")
    if pdf=="split.pdf" and table=="投资净收益": raise RuntimeError("table not found")
    if pdf=="flaky.pdf" and attempts[key]==1: raise RuntimeError("temporary parser failure")
    return {"capture_id":f"CAP_{pdf}_{table}","result":{"boundary_status":"HARD_BOUNDARY_CONFIRMED","header_dimension_status":"AUTO_CONFIRMED"}}

runner=TableCaptureRunner(job_service=backend.job_service,capture_service=backend.capture_service,audit_dir=paths["table_captures"],capture_callable=fake_capture)
jobs=runner.enqueue(pdf_paths=[legacy,split],family=INVESTMENT_RETURN_FAMILY,batch_id="BATCH_FAMILY",options={"max_pages":8})
assert len(jobs)==6
summary=runner.run(batch_id="BATCH_FAMILY",max_workers=2)
assert summary["counts"].get("SUCCESS")==3 and summary["counts"].get("SKIPPED")==3
assert summary["complete"]==6 and not summary["is_running"]

flaky_jobs=runner.enqueue(pdf_paths=[flaky],family=INVESTMENT_RETURN_FAMILY,batch_id="BATCH_RETRY",options={})
runner.run(batch_id="BATCH_RETRY",max_workers=3)
before=runner.monitor("BATCH_RETRY")
assert before["counts"].get("FAILED")==3, "失败必须被隔离并持久化"
retry=runner.retry_failed(batch_id="BATCH_RETRY",max_workers=2)
assert len(retry)==3
for _ in range(80):
    after=runner.monitor("BATCH_RETRY")
    if not after["is_running"]: break
    time.sleep(.05)
after=runner.monitor("BATCH_RETRY")
assert after["counts"].get("SUCCESS",0)>=3
assert (paths["table_captures"] / "batch_jobs" / "BATCH_FAMILY.json").exists()
assert (paths["table_captures"] / "batch_jobs" / "BATCH_FAMILY_summary.json").exists()
print("MULTI_PDF_CONTROLLED_WORKERS_PASS")
print("TABLE_FAMILY_SCHEMA_VARIANT_PASS")
print("PERSISTENT_FAILURE_ISOLATION_AND_RETRY_PASS")
print("BATCH_PROGRESS_AUDIT_ARTIFACTS_PASS")
