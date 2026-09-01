from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
from typing import Any
from metadata_registry import MetadataRegistry
from registry_sync import RegistrySynchronizer


class RegistryService:
    def __init__(self,registry:MetadataRegistry,synchronizer:RegistrySynchronizer,paths:dict[str,Path]):
        self.registry=registry;self.synchronizer=synchronizer;self.paths=paths
    def bootstrap_if_needed(self)->dict[str,Any]:
        out=self.synchronizer.bootstrap_if_needed()
        if out.get('bootstrapped'):
            reports=Path(self.paths['asset_reports']);reports.mkdir(parents=True,exist_ok=True)
            p=reports/f"registry_bootstrap_v61_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
            p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
            out['report_path']=str(p)
        return out
    def full_sync(self,reason:str='USER_REQUESTED_SYNC')->dict[str,Any]:return self.synchronizer.sync_all(reason=reason)
    def stats(self)->dict[str,Any]:
        return {'db_path':str(self.registry.db_path),'last_full_sync_at':self.registry.get_meta('last_full_sync_at'),'counts':self.registry.table_counts()}
