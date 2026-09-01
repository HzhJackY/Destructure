from __future__ import annotations
from typing import Any
from metadata_registry import MetadataRegistry


class BatchRepository:
    def __init__(self, registry: MetadataRegistry): self.registry=registry

    def list(self, *, include_fully_trashed: bool=False, only_with_trash: bool=False, limit:int=1000) -> list[dict[str,Any]]:
        where=[];params=[]
        if not include_fully_trashed: where.append("batch_status<>'TRASHED'")
        if only_with_trash: where.append('trashed_count>0')
        sql='SELECT * FROM capture_batches'
        if where:sql+=' WHERE '+' AND '.join(where)
        sql+=' ORDER BY COALESCE(last_created_at,updated_at) DESC LIMIT ?';params.append(int(limit))
        with self.registry.connect() as conn:rows=conn.execute(sql,params).fetchall()
        return [dict(r) for r in rows]

    def get(self,batch_id:str):
        with self.registry.connect() as conn:r=conn.execute('SELECT * FROM capture_batches WHERE batch_id=?',(str(batch_id),)).fetchone()
        return dict(r) if r else None

    def capture_ids(self,batch_id:str,*,include_trash:bool=False)->list[str]:
        sql='SELECT capture_id FROM captures WHERE batch_id=?'
        params=[str(batch_id)]
        if not include_trash:sql+=" AND is_trashed=0 AND lifecycle_status<>'TRASHED'"
        sql+=' ORDER BY COALESCE(created_at,updated_at)'
        with self.registry.connect() as conn:rows=conn.execute(sql,params).fetchall()
        return [str(r['capture_id']) for r in rows]
