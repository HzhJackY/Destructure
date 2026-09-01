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
        self.registry=registry;self.capture_repo=capture_repo;self.synchronizer=synchronizer;self.paths={k:Path(v) for k,v in paths.items()}

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
        self.synchronizer.sync_merges();self.registry.rebuild_batch_summaries()
        self.registry.event('BULK_INVALIDATE',asset_type='CAPTURE',payload={'capture_ids':ids,'reason_code':reason_code,'note':note,'result':out})
        return out

    def reactivate(self,capture_ids:Iterable[str])->dict[str,Any]:
        from asset_management import reactivate_captures, refresh_merge_dependency_statuses
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids);out=reactivate_captures(paths)
        refresh_merge_dependency_statuses(self.paths['table_captures'],self.paths['table_merges'])
        for p in paths:sync_capture_run(p)
        self.synchronizer.sync_merges();self.registry.rebuild_batch_summaries();self.registry.event('BULK_REACTIVATE',asset_type='CAPTURE',payload={'capture_ids':ids})
        return out

    def trash(self,capture_ids:Iterable[str])->dict[str,Any]:
        from asset_management import trash_captures
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids)
        out=trash_captures(paths,self.paths['table_capture_trash'],merge_root=self.paths['table_merges'])
        for moved in out.get('trashed') or []:sync_capture_run(Path(moved))
        self.synchronizer.sync_merges();self.registry.rebuild_batch_summaries();self.registry.event('BULK_TRASH',asset_type='CAPTURE',payload={'capture_ids':ids})
        return out

    def restore(self,capture_ids:Iterable[str])->dict[str,Any]:
        from asset_management import restore_trashed_captures, refresh_merge_dependency_statuses
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids)
        out=restore_trashed_captures(paths,self.paths['table_captures'])
        for moved in out.get('restored') or []:sync_capture_run(Path(moved))
        refresh_merge_dependency_statuses(self.paths['table_captures'],self.paths['table_merges']);self.synchronizer.sync_merges();self.registry.rebuild_batch_summaries()
        self.registry.event('BULK_RESTORE',asset_type='CAPTURE',payload={'capture_ids':ids});return out

    def purge(self,capture_ids:Iterable[str])->dict[str,Any]:
        from asset_management import purge_trashed_captures
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids);out=purge_trashed_captures(paths)
        for cid in ids:self.registry.delete_capture(cid)
        self.registry.rebuild_batch_summaries();self.registry.event('BULK_PURGE',asset_type='CAPTURE',payload={'capture_ids':ids});return out

    def rerun(self,capture_ids:Iterable[str],*,parser_mode:str='AUTO',batch_id:Optional[str]=None,progress_callback=None)->dict[str,Any]:
        from asset_management import rerun_capture_assets,new_batch_id
        ids=list(map(str,capture_ids));paths=self._paths_for_ids(ids);batch_id=batch_id or new_batch_id('RERUN_BATCH')
        out=rerun_capture_assets(paths,capture_root=self.paths['table_captures'],upload_root=self.paths['uploads'],parser_mode=parser_mode,batch_id=batch_id,progress_callback=progress_callback)
        for p in paths:
            if p.exists():sync_capture_run(p)
        for p in out.get('created') or []:sync_capture_run(Path(p))
        self.registry.rebuild_batch_summaries();self.registry.event('BULK_RERUN',asset_type='CAPTURE',payload={'capture_ids':ids,'new_batch_id':batch_id,'result':out});return out

    def export_inventory(self,rows:list[dict[str,Any]])->Path:
        outdir=self.paths['asset_reports'];outdir.mkdir(parents=True,exist_ok=True)
        path=outdir/f"asset_inventory_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.csv"
        import pandas as pd
        pd.DataFrame(rows).to_csv(path,index=False,encoding='utf-8-sig');return path
