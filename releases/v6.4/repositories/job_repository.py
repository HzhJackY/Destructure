from __future__ import annotations
import json
from typing import Any, Optional
from metadata_registry import MetadataRegistry, now_iso


class JobRepository:
    def __init__(self,registry:MetadataRegistry):self.registry=registry
    def create(self,row:dict[str,Any])->dict[str,Any]:self.registry.create_job(row);return self.get(str(row['job_id']))
    def get(self,job_id:str)->Optional[dict[str,Any]]:
        with self.registry.connect() as conn:r=conn.execute('SELECT * FROM jobs WHERE job_id=?',(str(job_id),)).fetchone()
        return self._row(r) if r else None
    @staticmethod
    def _row(r):
        d=dict(r)
        for src,dst in [('payload_json','payload'),('result_json','result')]:
            try:d[dst]=json.loads(d.get(src) or '{}')
            except Exception:d[dst]={}
        return d
    def list(self,*,batch_id:Optional[str]=None,status:Optional[str]=None,limit:int=500)->list[dict[str,Any]]:
        where=[];params=[]
        if batch_id:where.append('batch_id=?');params.append(str(batch_id))
        if status:where.append('status=?');params.append(str(status))
        sql='SELECT * FROM jobs'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY created_at DESC LIMIT ?';params.append(int(limit))
        with self.registry.connect() as conn:rows=conn.execute(sql,params).fetchall()
        return [self._row(r) for r in rows]
