from __future__ import annotations
import json
from typing import Any
from metadata_registry import MetadataRegistry


class MergeRepository:
    def __init__(self, registry:MetadataRegistry):self.registry=registry
    @staticmethod
    def _row(r):
        d=dict(r);d['run_id']=d.get('merge_id');d['run_dir']=d.get('run_path');d['is_trashed']=bool(d.get('is_trashed'))
        try:d['stale_capture_run_ids']=json.loads(d.get('stale_capture_run_ids_json') or '[]')
        except Exception:d['stale_capture_run_ids']=[]
        return d
    def list(self,*,include_trash:bool=False,only_trash:bool=False,limit:int=1000)->list[dict[str,Any]]:
        where=[]
        if only_trash:where.append('is_trashed=1')
        elif not include_trash:where.append('is_trashed=0')
        sql='SELECT * FROM merge_projects'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY COALESCE(created_at,updated_at) DESC LIMIT ?'
        with self.registry.connect() as conn:rows=conn.execute(sql,(int(limit),)).fetchall()
        return [self._row(r) for r in rows]
    def source_capture_ids(self,merge_id:str)->list[str]:
        with self.registry.connect() as conn:rows=conn.execute('SELECT capture_id FROM merge_sources WHERE merge_id=? ORDER BY source_order',(str(merge_id),)).fetchall()
        return [str(r['capture_id']) for r in rows]
