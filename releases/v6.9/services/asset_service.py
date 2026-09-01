from __future__ import annotations
import csv
import datetime as dt
from pathlib import Path
from typing import Any, Iterable, Optional

from metadata_registry import MetadataRegistry
from repositories.capture_repository import CaptureRepository
from registry_sync import RegistrySynchronizer
from registry_bridge import sync_capture_run, sync_merge_run


class AssetService:
    """Transactional-ish façade around legacy file mutations + SQLite index updates.

    File/JSON evidence stays authoritative. Every mutation updates legacy files first,
    then reconciles the metadata registry. If registry update fails, a full sync can
    rebuild it without losing evidence.
    """
    def __init__(self,registry:MetadataRegistry,capture_repo:CaptureRepository,synchronizer:RegistrySynchronizer,paths:dict[str,Path]):
        self.registry=registry;self.capture_repo=capture_repo;self.synchronizer=synchronizer;self.paths={k:Path(v) for k,v in paths.items()};self.capture_service=None
    def configure(self, *, capture_service, governance_repository=None):
        self.capture_service=capture_service;self.governance_repository=governance_repository

    def list_captures(self,**filters)->list[dict[str,Any]]:return self.capture_repo.list(**filters)
    def count_captures(self,**filters)->int:return self.capture_repo.count(**filters)
    def matching_capture_ids(self,**filters)->list[str]:return self.capture_repo.list_ids(**filters)
    def filter_options(self):
        return {k:self.capture_repo.distinct_values(k) for k in ['lifecycle_status','table_query','company','document_year','producer_version','batch_id','header_parser']}

    def _paths_for_ids(self,capture_ids:Iterable[str])->list[Path]:
        return [Path(r['run_path']) for r in self.capture_repo.get_many(list(map(str,capture_ids))) if r.get('run_path')]

    def dependency_impact(self,capture_ids:Iterable[str])->dict[str,Any]:
        ids=list(map(str,capture_ids));deps=self.capture_repo.dependent_merges(ids)
        return {'capture_count':len(ids),'dependent_merge_count':len(deps),'dependent_merges':deps}

    def invalidate(self,capture_ids:Iterable[str],*,reason_code:str,note:str='')->dict[str,Any]:
        from asset_management import invalidate_captures
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids)
        out=invalidate_captures(paths,reason_code=reason_code,note=note,merge_root=self.paths['table_merges'])
        for p in paths:sync_capture_run(p)
        if getattr(self,'governance_repository',None):
            self.governance_repository.set_capture_lifecycle(ids,status='INVALIDATED',actor='USER',reason=reason_code)
        self.synchronizer.sync_merges();self.registry.rebuild_batch_summaries()
        self.registry.event('BULK_INVALIDATE',asset_type='CAPTURE',payload={'capture_ids':ids,'reason_code':reason_code,'note':note,'result':out})
        return out

    def reactivate(self,capture_ids:Iterable[str])->dict[str,Any]:
        from asset_management import reactivate_captures, refresh_merge_dependency_statuses
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids);out=reactivate_captures(paths)
        refresh_merge_dependency_statuses(self.paths['table_captures'],self.paths['table_merges'])
        for p in paths:sync_capture_run(p)
        if getattr(self,'governance_repository',None):
            self.governance_repository.set_capture_lifecycle(ids,status='ACTIVE',actor='USER',reason='REACTIVATE',restore=True)
        self.synchronizer.sync_merges();self.registry.rebuild_batch_summaries();self.registry.event('BULK_REACTIVATE',asset_type='CAPTURE',payload={'capture_ids':ids})
        return out

    def trash(self,capture_ids:Iterable[str])->dict[str,Any]:
        from asset_management import trash_captures
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids)
        out=trash_captures(paths,self.paths['table_capture_trash'],merge_root=self.paths['table_merges'])
        for moved in out.get('trashed') or []:sync_capture_run(Path(moved))
        if getattr(self,'governance_repository',None):
            self.governance_repository.set_capture_lifecycle(ids,status='TRASHED',actor='USER',reason='TRASH')
        self.synchronizer.sync_merges();self.registry.rebuild_batch_summaries();self.registry.event('BULK_TRASH',asset_type='CAPTURE',payload={'capture_ids':ids})
        return out

    def restore(self,capture_ids:Iterable[str])->dict[str,Any]:
        from asset_management import restore_trashed_captures, refresh_merge_dependency_statuses
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids)
        out=restore_trashed_captures(paths,self.paths['table_captures'])
        for moved in out.get('restored') or []:sync_capture_run(Path(moved))
        if getattr(self,'governance_repository',None):
            self.governance_repository.set_capture_lifecycle(ids,status='ACTIVE',actor='USER',reason='RESTORE',restore=True)
        refresh_merge_dependency_statuses(self.paths['table_captures'],self.paths['table_merges']);self.synchronizer.sync_merges();self.registry.rebuild_batch_summaries()
        self.registry.event('BULK_RESTORE',asset_type='CAPTURE',payload={'capture_ids':ids});return out

    def purge(self,capture_ids:Iterable[str])->dict[str,Any]:
        from asset_management import purge_trashed_captures
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids);out=purge_trashed_captures(paths)
        for cid in ids:self.registry.delete_capture(cid)
        self.registry.rebuild_batch_summaries();self.registry.event('BULK_PURGE',asset_type='CAPTURE',payload={'capture_ids':ids});return out

    def rerun(self,capture_ids:Iterable[str],*,parser_mode:str='AUTO',batch_id:Optional[str]=None,progress_callback=None)->dict[str,Any]:
        from asset_management import new_batch_id
        from capture_models import CaptureMode,CaptureRequest
        if self.capture_service is None: raise RuntimeError('CAPTURE_ORCHESTRATOR_NOT_CONFIGURED')
        ids=list(map(str,capture_ids));batch_id=batch_id or new_batch_id('RERUN_BATCH')
        created=[];failures=[]
        for record in self.capture_repo.get_many(ids):
            try:
                run_dir=Path(record['run_path'])
                import json
                result=json.loads((run_dir/'table_capture_result.json').read_text(encoding='utf-8'))
                meta_path=run_dir/'capture_metadata.json'
                meta=json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
                source=str(meta.get('source_pdf_path') or (result.get('stats') or {}).get('source_pdf_path') or '')
                if not source: raise FileNotFoundError('原始 PDF 路径不可用')
                start=int(result.get('start_page') or 1);end=int(result.get('end_page') or start)
                request=CaptureRequest.new(
                    capture_mode=CaptureMode.MANUAL_ROI,source_pdf_path=source,
                    member_table_id=str(meta.get('member_table') or result.get('table_query') or ''),
                    table_family_id=str(meta.get('table_family') or ''),
                    manual_page_range=(start,start),retry_of_request_id=str(record['capture_id']),
                    request_metadata={
                        'table_query':result.get('table_query'),'note_number':result.get('note_number'),
                        'max_pages':max(2,end-start+3),'header_parser_mode':parser_mode,
                        'batch_id':batch_id,'rerun_of_capture_id':record['capture_id'],
                        'member_table_role':meta.get('member_table_role'),
                        'source_table_title':meta.get('source_table_title'),
                    },
                )
                output=self.capture_service.submit(request)
                if output.get('capture_id'):created.append(output['run_path'])
                else:failures.append({'capture_id':record['capture_id'],'reason':output})
            except Exception as exc:
                failures.append({'capture_id':record['capture_id'],'reason':f'{type(exc).__name__}:{exc}'})
        out={'batch_id':batch_id,'created':created,'failures':failures}
        self.registry.rebuild_batch_summaries();self.registry.event('BULK_RERUN',asset_type='CAPTURE',payload={'capture_ids':ids,'new_batch_id':batch_id,'result':out});return out

    def export_inventory(self,rows:list[dict[str,Any]])->Path:
        outdir=self.paths['asset_reports'];outdir.mkdir(parents=True,exist_ok=True)
        path=outdir/f"asset_inventory_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.csv"
        import pandas as pd
        pd.DataFrame(rows).to_csv(path,index=False,encoding='utf-8-sig');return path
