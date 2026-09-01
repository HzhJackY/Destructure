from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Optional

from repositories.capture_repository import CaptureRepository
from registry_bridge import sync_capture_run
from capture_models import CaptureMode, CaptureRequest, ResolvedCaptureTarget


class CaptureService:
    """Headless Capture use-cases shared by CLI/future FastAPI/Streamlit."""
    def __init__(self,repo:CaptureRepository,paths:dict[str,Path]):
        self.repo=repo;self.paths={k:Path(v) for k,v in paths.items()}
        self.orchestrator=None;self.runner=None
    def configure(self, *, orchestrator, runner=None):
        self.orchestrator=orchestrator;self.runner=runner
    def submit(self, request:CaptureRequest, *, asynchronous:bool=False):
        if self.orchestrator is None: raise RuntimeError("CAPTURE_ORCHESTRATOR_NOT_CONFIGURED")
        if asynchronous:
            if self.runner is None: raise RuntimeError("CAPTURE_RUNNER_NOT_CONFIGURED")
            return self.runner.enqueue_requests([request])
        return self.orchestrator.execute(request)
    def submit_batch(self, requests:list[CaptureRequest], *, batch_id:str|None=None,
                     max_workers:int=3, asynchronous:bool=True):
        if not asynchronous:
            return [self.submit(request) for request in requests]
        if self.runner is None: raise RuntimeError("CAPTURE_RUNNER_NOT_CONFIGURED")
        jobs=self.runner.enqueue_requests(requests,batch_id=batch_id)
        if jobs:self.runner.start(batch_id=jobs[0]["batch_id"],max_workers=max_workers)
        return jobs
    def execute_queued_request(self, request:CaptureRequest):
        if self.orchestrator is None: raise RuntimeError("CAPTURE_ORCHESTRATOR_NOT_CONFIGURED")
        return self.orchestrator.execute(request)
    def retry(self, job_id_or_request, **overrides):
        if isinstance(job_id_or_request,CaptureRequest):
            request=job_id_or_request
        else:
            if self.runner is None:raise RuntimeError("CAPTURE_RUNNER_NOT_CONFIGURED")
            job=self.runner.job_service.get(str(job_id_or_request))
            if not job:raise KeyError(job_id_or_request)
            request=CaptureRequest.from_dict((job.get("payload") or {})["capture_request"])
        payload=request.to_dict();payload.update(overrides)
        payload["request_id"]="CREQ_"+dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
        payload["capture_mode"]=CaptureMode.FAILED_JOB_RETRY.value
        payload["retry_of_request_id"]=request.request_id
        return self.submit(CaptureRequest.from_dict(payload))
    def rerun(self, logical_asset_id:str, options:dict[str,Any]|None=None, *, requested_by:str="USER"):
        if self.orchestrator is None:raise RuntimeError("CAPTURE_ORCHESTRATOR_NOT_CONFIGURED")
        versions=self.orchestrator.repo.capture_versions(logical_asset_id)
        current=next((row for row in versions if row["is_current"]),None)
        if not current:raise KeyError(f"NO_CURRENT_CAPTURE:{logical_asset_id}")
        capture_id=str(current["capture_id"]);record=self.repo.get(capture_id)
        if not record:raise KeyError(capture_id)
        run_dir=Path(record["run_path"])
        evidence=json.loads((run_dir/"table_capture_result.json").read_text(encoding="utf-8"))
        metadata_path=run_dir/"capture_metadata.json"
        metadata=json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        source=str(metadata.get("source_pdf_path") or (evidence.get("stats") or {}).get("source_pdf_path") or "")
        if not source:raise FileNotFoundError("SOURCE_PDF_PATH_REQUIRED")
        start=int(evidence.get("start_page") or 1)
        request=CaptureRequest.new(
            capture_mode=CaptureMode.MANUAL_ROI,source_pdf_path=source,
            member_table_id=str(metadata.get("member_table") or record.get("table_query") or ""),
            table_family_id=str(metadata.get("table_family") or ""),
            manual_page_range=(start,start),requested_by=requested_by,
            retry_of_request_id=capture_id,
            request_metadata={
                **dict(options or {}),"table_query":evidence.get("table_query") or record.get("table_query"),
                "rerun_of_capture_id":capture_id,"member_table_role":metadata.get("member_table_role"),
            },
        )
        return self.submit(request)
    def list(self,**filters)->list[dict[str,Any]]:return self.repo.list(**filters)
    def count(self,**filters)->int:return self.repo.count(**filters)
    def get(self,capture_id:str):return self.repo.get(capture_id)
    def register_run(self,run_dir:Path):
        sync=sync_capture_run(run_dir)
        if sync.get("status")!="OK":
            raise RuntimeError(f"CAPTURE_REGISTRY_SYNC_FAILED: {sync}")
        registered=self.repo.get(Path(run_dir).name)
        if registered is None:
            raise RuntimeError(f"CAPTURE_REGISTRY_RECORD_MISSING: {Path(run_dir).name}")
        return registered
    def filter_options(self)->dict[str,list[str]]:
        return {k:self.repo.distinct_values(k) for k in ['lifecycle_status','table_query','company','document_year','producer_version','batch_id','header_parser']}

    def create(
        self, *, pdf_path:Path, table_query:str, note_number:Optional[str]=None,
        start_page_override:Optional[int]=None, max_pages:int=8,
        header_parser_mode:str='AUTO', batch_id:Optional[str]=None,
        output_dir:Optional[Path]=None, progress_callback=None,
        guided_target_required:bool=False, certified_note_target:dict[str,Any]|None=None,
        table_family:str|None=None, member_table:str|None=None,
        member_table_role:str|None=None, source_table_title:str|None=None,
        note_reference:str|None=None, member_table_order:int|None=None,
    )->dict[str,Any]:
        """Compatibility adapter: all callers now enter the unified orchestrator."""
        certified=dict(certified_note_target or {})
        if start_page_override and not certified:
            certified={
                "confirmed_note_pdf_page_index":int(start_page_override),
                "target_heading":str(table_query),"capture_query_title":str(table_query),
                "note_reference":str(note_reference or note_number or ""),
                "status":"MANUAL_CERTIFIED","confidence":1.0,
            }
        mode=CaptureMode.CERTIFIED_TARGET if certified else CaptureMode.DIRECT_DISCLOSURE
        request=CaptureRequest.new(
            capture_mode=mode,source_pdf_path=str(Path(pdf_path).resolve()),
            member_table_id=str(member_table or table_query),
            table_family_id=str(table_family or ""),
            manual_page_range=None,
            request_metadata={
                "table_query":str(table_query),"note_number":note_number,
                "max_pages":int(max_pages),"header_parser_mode":header_parser_mode,
                "batch_id":batch_id,"output_dir":str(output_dir) if output_dir else "",
                "guided_target_required":bool(guided_target_required),
                "certified_target":certified,"member_table_role":member_table_role,
                "source_table_title":source_table_title,"note_reference":note_reference,
                "member_table_order":member_table_order,
            },
        )
        return self.submit(request)

    def _execute_resolved_target(
        self, request:CaptureRequest, target:ResolvedCaptureTarget,
    )->dict[str,Any]:
        options=dict(request.capture_options);options.update(request.request_metadata)
        direct_full_book=target.target_type=="DIRECT_DISCLOSURE" and bool(target.evidence.get("full_book_query"))
        return self._create_legacy(
            pdf_path=Path(request.source_pdf_path),
            table_query=str(target.title or request.member_table_id or options.get("table_query")),
            note_number=target.note_reference or options.get("note_number"),
            start_page_override=None if direct_full_book else target.start_page,max_pages=int(options.get("max_pages",8)),
            header_parser_mode=str(options.get("header_parser_mode") or "AUTO"),
            batch_id=options.get("batch_id"),output_dir=Path(options["output_dir"]) if options.get("output_dir") else None,
            guided_target_required=not direct_full_book,
            certified_note_target={
                "status":"CERTIFIED_NOTE_TARGET",
                "confirmed_note_pdf_page_index":target.start_page,
                "target_heading":target.title,
            },
            table_family=request.table_family_id,member_table=request.member_table_id,
            member_table_role=options.get("member_table_role"),
            source_table_title=options.get("source_table_title"),
            note_reference=target.note_reference or options.get("note_reference"),
            member_table_order=options.get("member_table_order"),
        )

    def _create_legacy(
        self,
        *,
        pdf_path:Path,
        table_query:str,
        note_number:Optional[str]=None,
        start_page_override:Optional[int]=None,
        max_pages:int=8,
        header_parser_mode:str='AUTO',
        batch_id:Optional[str]=None,
        output_dir:Optional[Path]=None,
        progress_callback=None, guided_target_required: bool=False, certified_note_target: dict[str,Any]|None=None,
        table_family: str | None = None, member_table: str | None = None,
        member_table_role: str | None = None, source_table_title: str | None = None,
        note_reference: str | None = None, member_table_order: int | None = None,
    )->dict[str,Any]:
        """Create one audited table Capture without importing any UI framework."""
        from table_capture import capture_named_table,write_capture_artifacts
        if guided_target_required:
            target=dict(certified_note_target or {})
            if target.get("status")!="CERTIFIED_NOTE_TARGET" or not target.get("confirmed_note_pdf_page_index"):
                raise PermissionError("NO_UNCERTIFIED_FULLBOOK_FALLBACK")
            if int(start_page_override or 0)!=int(target["confirmed_note_pdf_page_index"]):
                raise PermissionError("CERTIFIED_TARGET_PAGE_MISMATCH")
        from capture_library import initialize_capture_library_run
        try:
            from batch_pipeline import display_pdf_name
        except Exception:
            display_pdf_name=lambda x:str(x)
        pdf_path=Path(pdf_path)
        # Register source metadata before Capture insert so the SQLite FK can be
        # resolved even when this service is used headlessly outside Streamlit.
        try:
            from batch_pipeline import display_pdf_name, infer_company_year
            display = display_pdf_name(pdf_path.name)
            company, year = infer_company_year(Path(display), "")
            self.repo.registry.upsert_pdf({
                "pdf_id": "PDF::" + str(pdf_path.resolve()).lower(),
                "filename": pdf_path.name,
                "display_name": display,
                "company": company,
                "document_year": year,
                "size_bytes": pdf_path.stat().st_size,
                "path": str(pdf_path.resolve()),
                "modified_at": dt.datetime.fromtimestamp(pdf_path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            })
        except Exception:
            pass
        if output_dir is None:
            stamp=dt.datetime.now().strftime('%Y%m%dT%H%M%S_%f')
            source=re.sub(r'[\\/:*?"<>|]+','_',Path(display_pdf_name(pdf_path.name)).stem)[:65]
            title=re.sub(r'[\\/:*?"<>|]+','_',str(table_query).strip())[:55]
            output_dir=self.paths['table_captures']/f'{source}__{title}__{stamp}'
        output_dir=Path(output_dir)
        if str(member_table_role or "").upper() == "STATEMENT_ANCHOR":
            # Statement anchors have their header above the display_name.  A
            # note-table ROI starts below the title and would otherwise lose
            # its scope/year columns.
            from statement_anchor_capture import capture_statement_anchor
            result = capture_statement_anchor(pdf_path, str(table_query).strip(), int(start_page_override or 1), note_number=note_number)
        else:
            result=capture_named_table(
                pdf_path=pdf_path,table_query=str(table_query).strip(),note_number=note_number,
                start_page_override=start_page_override,max_pages=int(max_pages),progress_callback=progress_callback,
                header_parser_mode=header_parser_mode,
                allow_legacy_fallback=not guided_target_required,
                strict_target_identity=guided_target_required,
                certified_target_heading=(
                    str((certified_note_target or {}).get("target_heading") or table_query)
                    if guided_target_required else None
                ),
            )
        # v6.9 keeps the existing capture primitive as the only extraction
        # entrypoint, then turns a compound note into independently auditable
        # child blocks.  A single-table note remains exactly one child.
        from compound_note_engine import materialize_block_result, segment_table_blocks, serialise_block
        container, blocks = segment_table_blocks(result)
        bundle_id = f"BUNDLE_{container.container_id.split('_', 1)[-1]}"
        child_runs: list[dict[str, Any]] = []
        primary_output_dir = output_dir
        for block in blocks:
            child_result = materialize_block_result(result, block)
            suffix = re.sub(r'[^0-9A-Za-z_\-]+', '_', block.title)[:35] or f"block_{block.block_order + 1}"
            child_dir = primary_output_dir if block.block_order == 0 else primary_output_dir.with_name(
                f"{primary_output_dir.name}__b{block.block_order + 1}_{suffix}"
            )
            artifacts = write_capture_artifacts(child_dir, child_result)
            child_runs.append({"block": block, "run_dir": child_dir, "result": child_result, "artifacts": artifacts})
        # The first block is retained as the compatibility capture result.
        output_dir = child_runs[0]["run_dir"]
        result = child_runs[0]["result"]
        artifacts = child_runs[0]["artifacts"]
        metadata=initialize_capture_library_run(
            output_dir,source_pdf_display=display_pdf_name(pdf_path.name),table_query=str(table_query).strip(),batch_id=batch_id,
        )
        # Preserve the Table Family identity at the Capture boundary.  Machine
        # table evidence remains immutable; this is source provenance required
        # by the downstream Family Merge observation contract.
        metadata_path = output_dir / "capture_metadata.json"
        persisted = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else dict(metadata)
        persisted.update({
            "table_family": str(table_family or persisted.get("table_family") or "").strip(),
            "member_table": str(member_table or persisted.get("member_table") or table_query).strip(),
            "member_table_role": str(member_table_role or persisted.get("member_table_role") or "COMPONENT").strip(),
            "source_table_title": str(source_table_title or persisted.get("source_table_title") or member_table or table_query).strip(),
            "note_reference": str(note_reference or persisted.get("note_reference") or note_number or "").strip(),
            "member_table_order": member_table_order if member_table_order is not None else persisted.get("member_table_order"),
            "source_pdf_path": str(pdf_path.resolve()),
        })
        metadata_path.write_text(json.dumps(persisted, ensure_ascii=False, indent=2), encoding="utf-8")
        metadata = persisted
        sync=sync_capture_run(output_dir)
        if sync.get("status")!="OK":
            raise RuntimeError(f"CAPTURE_REGISTRY_SYNC_FAILED: {sync}")
        if self.repo.get(output_dir.name) is None:
            raise RuntimeError(f"CAPTURE_REGISTRY_RECORD_MISSING: {output_dir.name}")
        # Persist the immutable container/block graph after physical child
        # captures are registered.  Failed auxiliary persistence must never
        # hide a successful primary capture, but is visible in machine metadata.
        child_payloads=[]
        try:
            import uuid
            now=dt.datetime.now().astimezone().isoformat(timespec="seconds")
            with self.repo.registry.connect() as conn:
                conn.execute("""INSERT OR REPLACE INTO note_containers
                    (container_id,source_pdf_id,source_pdf_sha256,source_pdf_path,note_reference,note_title,start_pdf_page,end_pdf_page,context_json,layout_graph_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
                    container.container_id, "PDF::" + str(pdf_path.resolve()).lower(), container.source_pdf_sha256,
                    str(pdf_path.resolve()), container.note_reference, container.note_title, container.start_pdf_page,
                    container.end_pdf_page, json.dumps(dict(result.document_context or {}),ensure_ascii=False),
                    json.dumps(container.layout_evidence,ensure_ascii=False), now))
                conn.execute("""INSERT OR REPLACE INTO capture_bundles
                    (bundle_id,request_id,container_id,table_family_id,member_table_id,status,payload_json,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?)""", (bundle_id, None, container.container_id, table_family, member_table,
                    "COMPLETED", json.dumps({"engine":"v6.9","block_count":len(blocks)},ensure_ascii=False),now,now))
                for child in child_runs:
                    block=child["block"]; child_dir=child["run_dir"]
                    if child_dir != output_dir:
                        child_meta=initialize_capture_library_run(child_dir,source_pdf_display=display_pdf_name(pdf_path.name),table_query=block.title,batch_id=batch_id)
                        child_meta_path=child_dir/'capture_metadata.json'
                        child_meta.update({"table_family":str(table_family or ""),"member_table":str(member_table or block.title),
                            "member_table_role":"NOTE_DETAIL" if block.block_order else str(member_table_role or "COMPONENT"),
                            "member_subtable_id":block.block_id,"capture_bundle_id":bundle_id,"source_pdf_path":str(pdf_path.resolve())})
                        child_meta_path.write_text(json.dumps(child_meta,ensure_ascii=False,indent=2),encoding='utf-8')
                        child_sync=sync_capture_run(child_dir)
                        if child_sync.get("status")!="OK": raise RuntimeError(f"CAPTURE_CHILD_REGISTRY_SYNC_FAILED:{child_sync}")
                    conn.execute("""INSERT OR REPLACE INTO table_blocks
                        (block_id,container_id,block_order,block_title,block_role,start_pdf_page,end_pdf_page,bbox_json,header_topology_json,semantic_graph_json,reconciliation_json,quality_status,status,evidence_json,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                        block.block_id,container.container_id,block.block_order,block.title,block.role,block.start_pdf_page,block.end_pdf_page,
                        json.dumps(block.bbox,ensure_ascii=False),json.dumps(block.header_topology,ensure_ascii=False),
                        json.dumps(block.semantic_graph,ensure_ascii=False),json.dumps(block.reconciliation,ensure_ascii=False),
                        block.quality_status,"CAPTURED",json.dumps(block.evidence,ensure_ascii=False),now))
                    conn.execute("""INSERT OR REPLACE INTO capture_bundle_children
                        (bundle_id,block_id,capture_id,logical_asset_id,child_order,status,payload_json,created_at)
                        VALUES(?,?,?,?,?,?,?,?)""", (bundle_id,block.block_id,child_dir.name,None,block.block_order,
                        "CAPTURED",json.dumps(serialise_block(block),ensure_ascii=False),now))
                    child_payloads.append({"capture_id":child_dir.name,"run_path":str(child_dir),"block":serialise_block(block)})
        except Exception as exc:
            metadata["v69_bundle_persistence_warning"]=f"{type(exc).__name__}:{exc}"
            (output_dir/'capture_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        metadata.update({"capture_bundle_id":bundle_id,"note_container_id":container.container_id,"v69_block_count":len(blocks),
                         "member_subtable_id":blocks[0].block_id})
        (output_dir/'capture_metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return {'capture_id':output_dir.name,'run_path':str(output_dir),'artifacts':artifacts,'metadata':metadata,
                'result':result.to_dict() if hasattr(result,'to_dict') else result,
                'capture_bundle_id':bundle_id,'note_container_id':container.container_id,'child_captures':child_payloads}
