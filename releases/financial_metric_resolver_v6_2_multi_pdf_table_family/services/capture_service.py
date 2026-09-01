from __future__ import annotations
import datetime as dt
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
    def register_run(self,run_dir:Path):sync_capture_run(run_dir);return self.repo.get(Path(run_dir).name)
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
        progress_callback=None,
    )->dict[str,Any]:
        """Create one audited table Capture without importing any UI framework."""
        from table_capture import capture_named_table,write_capture_artifacts
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
        )
        artifacts=write_capture_artifacts(output_dir,result)
        metadata=initialize_capture_library_run(
            output_dir,source_pdf_display=display_pdf_name(pdf_path.name),table_query=str(table_query).strip(),batch_id=batch_id,
        )
        sync_capture_run(output_dir)
        return {'capture_id':output_dir.name,'run_path':str(output_dir),'artifacts':artifacts,'metadata':metadata,'result':result.to_dict() if hasattr(result,'to_dict') else result}
