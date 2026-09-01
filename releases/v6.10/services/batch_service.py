from __future__ import annotations
from pathlib import Path
from typing import Any, Iterable
from repositories.batch_repository import BatchRepository
from services.asset_service import AssetService


class BatchService:
    def __init__(self,repo:BatchRepository,assets:AssetService):self.repo=repo;self.assets=assets
    def list_batches(self,*,include_fully_trashed:bool=False,only_with_trash:bool=False)->list[dict[str,Any]]:
        return self.repo.list(include_fully_trashed=include_fully_trashed,only_with_trash=only_with_trash)
    def capture_ids(self,batch_id:str,*,include_trash:bool=False)->list[str]:return self.repo.capture_ids(batch_id,include_trash=include_trash)
    def trashed_capture_ids(self,batch_id:str)->list[str]:
        return [r['capture_id'] for r in self.assets.capture_repo.list(batch_id=batch_id,only_trash=True,include_trash=True,limit=100000)]
    def selected_capture_ids(self,batch_ids:Iterable[str],*,include_trash:bool=False)->list[str]:
        out=[];seen=set()
        for bid in batch_ids:
            for cid in self.capture_ids(str(bid),include_trash=include_trash):
                if cid not in seen:seen.add(cid);out.append(cid)
        return out
    def invalidate(self,batch_ids:Iterable[str],*,reason_code:str,note:str=''):return self.assets.invalidate(self.selected_capture_ids(batch_ids),reason_code=reason_code,note=note)
    def trash(self,batch_ids:Iterable[str]):return self.assets.trash(self.selected_capture_ids(batch_ids))
    def rerun(self,batch_ids:Iterable[str],*,parser_mode:str='AUTO',batch_id:str|None=None):return self.assets.rerun(self.selected_capture_ids(batch_ids),parser_mode=parser_mode,batch_id=batch_id)
