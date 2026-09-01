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
from financial_structure_resolver import ensure_row_paths, subtotal_validation
from template_learning import HistoricalTemplateStore
from table_merge import assign_conditional_source_keys, materialize_canonical
import pandas as pd

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

# v6.2 financial-structure contract: identical labels in different branches
# must stay distinct, and subtotal checks must tolerate displayed rounding.
rows=[]
spec=[
    (1,"股息及利息收入",0,"",700945162.85),
    (2,"股息收入",1,"股息及利息收入",700945162.85),
    (3,"交易性金融资产",2,"股息收入",603897084.56),
    (4,"其他权益工具投资",2,"股息收入",97048078.29),
    (5,"利息收入",1,"股息及利息收入",0.004),
    (6,"交易性金融资产",2,"利息收入",0.004),
]
for order,item,level,parent,value in spec:
    rows.append({"row_order":order,"normalized_item":item,"raw_item":item,"parent_section":parent,"row_type":"DETAIL","row_level":level,"value":value,"unit":"元","column_ordinal":0,"table_id":"INVEST","table_family":"INVEST","member_table":"投资净收益","member_table_role":"COMPONENT","source_table_title":"利润表","note_reference":"附注九-1","source_pdf":"fixture.pdf","period_type":"ANNUAL","currency":"CNY","canonical_section":"","canonical_item":item,"company":"A","document_year":"2025","year":"2025","scope":"本集团","restated":False,"mapping_status":"UNMAPPED_PRESERVED","capture_run_id":"R1","page":1})
structure=ensure_row_paths(pd.DataFrame(rows))
same_name=structure[structure["normalized_item"]=="交易性金融资产"]
assert same_name["row_path"].nunique()==2, "重复行名必须由父路径区分"
audit=subtotal_validation(structure)
assert "PASS" in set(audit["status"]) or "PASS_WITH_ROUNDING" in set(audit["status"])
keyed=assign_conditional_source_keys(structure)
assert keyed[keyed["normalized_item"]=="交易性金融资产"]["source_key"].nunique()==2
print("ROW_PATH_REPEATED_LABEL_PRESERVATION_PASS")
print("UNIT_AWARE_ROUNDING_SUBTOTAL_PASS")

# Missing scope plus multiple physical columns is a review warning, whereas
# same fully-qualified key with distinct values remains a blocking conflict.
ambiguous=keyed[keyed["row_order"]==3].copy(); ambiguous=pd.concat([ambiguous, ambiguous.assign(column_ordinal=1, value=7.0)], ignore_index=True)
ambiguous["scope"]=""; ambiguous["canonical_key"]="RAW::INVEST::交易性金融资产::交易性金融资产"
resolved,_,conflicts=materialize_canonical(ambiguous)
assert "REVIEW_REQUIRED_DIMENSION_AMBIGUITY" in set(conflicts["conflict_status"])
assert set(conflicts["conflict_severity"])=={"WARNING"}
hard=ambiguous.copy(); hard["scope"]="本集团"; hard["column_ordinal"]=0
_,_,hard_conflicts=materialize_canonical(hard)
assert "VALUE_CONFLICT" in set(hard_conflicts["conflict_status"])
assert set(hard_conflicts["conflict_severity"])=={"BLOCKING"}
print("DIMENSION_AWARE_MERGE_WARNING_VS_BLOCK_PASS")

store=HistoricalTemplateStore(runtime / "templates" / "financial_structure_templates.json")
store.learn({"company":"A","table_id":"INVEST","document_year":"2024","row_paths":structure["row_path"].drop_duplicates().tolist()})
matches=store.retrieve({"company":"A","table_id":"INVEST","row_paths":structure["row_path"].drop_duplicates().tolist()})
assert matches and matches[0].score >= .9
print("HISTORICAL_TEMPLATE_RETRIEVAL_AND_ML_INTERFACE_PASS")
