"""Persistent, controlled-concurrency execution for multi-PDF table Capture."""
from __future__ import annotations
import json, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable
from services.table_family_service import TableFamily, detect_schema_variant

TERMINAL={"SUCCESS","REVIEW_REQUIRED","FAILED","CANCELLED","SKIPPED"}
NOT_FOUND_MARKERS=("未找到", "not found", "no table", "table title")

class TableCaptureRunner:
    def __init__(self, *, job_service, capture_service, audit_dir: Path, capture_callable: Callable | None = None):
        self.job_service=job_service; self.capture_service=capture_service; self.audit_dir=Path(audit_dir)
        self.capture_callable=capture_callable or capture_service.create; self._threads={}
    def enqueue(self, *, pdf_paths: Iterable[Path], family: TableFamily, batch_id: str, options: dict[str, Any]) -> list[dict]:
        jobs=[]
        for pdf_path in map(Path,pdf_paths):
            for target in family.targets:
                payload={"pdf_path":str(pdf_path.resolve()),"table_query":target.name,"target_role":target.role,"target_required":target.required,"family":family.to_dict(),"options":dict(options)}
                jobs.append(self.job_service.create("TABLE_CAPTURE",batch_id=batch_id,payload=payload))
        self._write_manifest(batch_id,family,jobs); return jobs
    def start(self, *, batch_id: str, max_workers: int=3) -> None:
        if batch_id in self._threads and self._threads[batch_id].is_alive(): return
        thread=threading.Thread(target=self.run,kwargs={"batch_id":batch_id,"max_workers":max_workers},daemon=True)
        self._threads[batch_id]=thread; thread.start()
    def run(self, *, batch_id: str, max_workers: int=3) -> dict:
        queued=[j for j in self.job_service.list(batch_id=batch_id,limit=100000) if j["status"]=="QUEUED"]
        with ThreadPoolExecutor(max_workers=max(1,min(int(max_workers),8)),thread_name_prefix="table-capture") as pool:
            futures=[pool.submit(self._run_one,job) for job in queued]
            for future in as_completed(futures): future.result()
        self._write_summary(batch_id); return self.monitor(batch_id)
    def retry_failed(self, *, batch_id: str, max_workers: int=3) -> list[dict]:
        created=[]
        for old in self.job_service.list(batch_id=batch_id,status="FAILED",limit=100000):
            payload=dict(old.get("payload") or {}); payload["retry_of_job_id"]=old["job_id"]
            created.append(self.job_service.create("TABLE_CAPTURE",batch_id=batch_id,payload=payload))
        if created:self.start(batch_id=batch_id,max_workers=max_workers)
        return created
    def monitor(self,batch_id:str)->dict:
        jobs=self.job_service.list(batch_id=batch_id,limit=100000); counts={}
        for job in jobs:counts[job["status"]]=counts.get(job["status"],0)+1
        total=len(jobs);complete=sum(counts.get(s,0) for s in TERMINAL)
        return {"batch_id":batch_id,"total":total,"complete":complete,"progress":complete/total if total else 1.0,"counts":counts,"is_running":bool(counts.get("RUNNING") or counts.get("QUEUED")),"jobs":jobs}
    def _run_one(self,job:dict)->None:
        payload=job.get("payload") or {}; self.job_service.update(job["job_id"],status="RUNNING",progress=.05)
        try:
            options=dict(payload.get("options") or {})
            result=self.capture_callable(pdf_path=Path(payload["pdf_path"]),table_query=payload["table_query"],note_number=options.get("note_number"),start_page_override=options.get("start_page_override"),max_pages=int(options.get("max_pages",8)),header_parser_mode=options.get("header_parser_mode","AUTO"),batch_id=job.get("batch_id"),progress_callback=None)
            evidence=result.get("result") or {}; review=evidence.get("boundary_status")=="REVIEW_REQUIRED" or evidence.get("header_dimension_status")=="REVIEW_REQUIRED"
            self.job_service.update(job["job_id"],status="REVIEW_REQUIRED" if review else "SUCCESS",progress=1.0,target_asset_id=result.get("capture_id"),result={"capture_id":result.get("capture_id"),"schema_role":payload.get("target_role")})
        except Exception as exc:
            if any(marker in str(exc).lower() for marker in NOT_FOUND_MARKERS): self.job_service.update(job["job_id"],status="SKIPPED",progress=1.0,result={"reason":"TABLE_NOT_FOUND","schema_role":payload.get("target_role")})
            else:self.job_service.update(job["job_id"],error=exc)
    def _write_manifest(self,batch_id,family,jobs):
        path=self.audit_dir/"batch_jobs";path.mkdir(parents=True,exist_ok=True)
        (path/f"{batch_id}.json").write_text(json.dumps({"batch_id":batch_id,"family":family.to_dict(),"job_ids":[x["job_id"] for x in jobs]},ensure_ascii=False,indent=2),encoding="utf-8")
    def _write_summary(self,batch_id):
        monitor=self.monitor(batch_id);groups={}
        for job in monitor["jobs"]:groups.setdefault((job.get("payload") or {}).get("pdf_path",""),[]).append(job)
        variants=[]
        for pdf,jobs in groups.items():variants.append({"pdf_path":pdf,"schema_variant":detect_schema_variant({"role":(j.get("payload") or {}).get("target_role"),"status":j["status"]} for j in jobs)})
        path=self.audit_dir/"batch_jobs"/f"{batch_id}_summary.json";path.write_text(json.dumps({"monitor":monitor|{"jobs":[]},"pdf_schema_variants":variants},ensure_ascii=False,indent=2),encoding="utf-8")
