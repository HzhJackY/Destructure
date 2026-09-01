from __future__ import annotations
import datetime as dt
from pathlib import Path
from typing import Any,Iterable,Optional
from repositories.merge_repository import MergeRepository
from repositories.capture_repository import CaptureRepository
from registry_sync import RegistrySynchronizer
from registry_bridge import sync_merge_run
from metadata_registry import MetadataRegistry


class MergeService:
    """Headless Merge/Taxonomy project façade."""
    def __init__(self,repo:MergeRepository,capture_repo:CaptureRepository,registry:MetadataRegistry,synchronizer:RegistrySynchronizer,paths:dict[str,Path]):
        self.repo=repo;self.capture_repo=capture_repo;self.registry=registry;self.synchronizer=synchronizer;self.paths={k:Path(v) for k,v in paths.items()}
    def list(self,*,include_trash:bool=False,only_trash:bool=False):return self.repo.list(include_trash=include_trash,only_trash=only_trash)
    def create(
        self,
        *,
        capture_ids:Iterable[str],
        table_id:str,
        metadata_rows:Optional[list[dict[str,Any]]]=None,
        reference_capture_id:Optional[str]=None,
        output_dir:Optional[Path]=None,
        taxonomy_path:Optional[Path]=None,
    )->dict[str,Any]:
        from table_merge import create_merge_project,infer_capture_metadata
        from merge_library import ensure_merge_metadata
        ids=list(map(str,capture_ids));records=self.capture_repo.get_many(ids)
        if len(records)!=len(ids):
            found={r['capture_id'] for r in records};missing=[x for x in ids if x not in found];raise KeyError(f'Missing Capture IDs: {missing}')
        dirs=[Path(r['run_path']) for r in records]
        if metadata_rows is None:
            metadata_rows=[infer_capture_metadata(d) for d in dirs]
        if output_dir is None:
            stamp=dt.datetime.now().strftime('%Y%m%dT%H%M%S_%f')
            output_dir=self.paths['table_merges']/f'{str(table_id)[:70]}__{stamp}'
        taxonomy_path=Path(taxonomy_path or self.paths['taxonomy'])
        artifacts=create_merge_project(dirs,metadata_rows,Path(output_dir),table_id,taxonomy_path,reference_capture_run_id=reference_capture_id)
        ensure_merge_metadata(Path(output_dir));sync_merge_run(Path(output_dir))
        return {'merge_id':Path(output_dir).name,'run_path':str(output_dir),'artifacts':artifacts}
    def refresh(self,merge_id:str,*,persist_taxonomy:bool=False)->dict[str,Any]:
        from table_merge import refresh_merge_project
        row=next((x for x in self.repo.list(include_trash=False) if str(x.get('merge_id'))==str(merge_id)),None)
        if row is None:raise KeyError(merge_id)
        artifacts=refresh_merge_project(Path(row['run_path']),persist_taxonomy=persist_taxonomy);sync_merge_run(Path(row['run_path']));return artifacts
    def refresh_dependencies(self):
        from asset_management import refresh_merge_dependency_statuses
        out=refresh_merge_dependency_statuses(self.paths['table_captures'],self.paths['table_merges']);self.synchronizer.sync_merges();return out
    def trash(self,merge_ids:Iterable[str]):
        from asset_management import trash_merges
        ids=set(map(str,merge_ids));rows=[r for r in self.repo.list(include_trash=False) if str(r.get('merge_id')) in ids]
        out=trash_merges([Path(r['run_path']) for r in rows],self.paths['merge_trash']);self.synchronizer.sync_merges();return out
    def restore(self,merge_ids:Iterable[str]):
        from asset_management import restore_merges
        ids=set(map(str,merge_ids));rows=[r for r in self.repo.list(include_trash=True,only_trash=True) if str(r.get('merge_id')) in ids]
        out=restore_merges([Path(r['run_path']) for r in rows],self.paths['table_merges']);self.synchronizer.sync_merges();return out
    def purge(self,merge_ids:Iterable[str]):
        from asset_management import purge_merges
        ids=list(map(str,merge_ids));rows=[r for r in self.repo.list(include_trash=True,only_trash=True) if str(r.get('merge_id')) in set(ids)]
        out=purge_merges([Path(r['run_path']) for r in rows])
        for mid in ids:self.registry.delete_merge(mid)
        return out
