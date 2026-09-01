from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Optional

from repositories.capture_repository import CaptureRepository
from registry_bridge import sync_capture_run


class CaptureService:
    """Headless Capture use-cases shared by CLI/future FastAPI/Streamlit."""
    def __init__(self,repo:CaptureRepository,paths:dict[str,Path]):
        self.repo=repo;self.paths={k:Path(v) for k,v in paths.items()}
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
        artifacts=write_capture_artifacts(output_dir,result)
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
        return {'capture_id':output_dir.name,'run_path':str(output_dir),'artifacts':artifacts,'metadata':metadata,'result':result.to_dict() if hasattr(result,'to_dict') else result}
