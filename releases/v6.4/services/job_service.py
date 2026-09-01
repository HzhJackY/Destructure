from __future__ import annotations
import datetime as dt
import uuid
from typing import Any, Optional
from repositories.job_repository import JobRepository

VALID_JOB_STATUSES={'QUEUED','RUNNING','SUCCESS','REVIEW_REQUIRED','FAILED','CANCELLED','SKIPPED'}


class JobService:
    def __init__(self,repo:JobRepository):self.repo=repo
    def create(self,job_type:str,*,batch_id:Optional[str]=None,source_asset_id:Optional[str]=None,payload:Optional[dict[str,Any]]=None)->dict[str,Any]:
        job_id=f"JOB_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
        return self.repo.create({'job_id':job_id,'batch_id':batch_id,'job_type':job_type,'status':'QUEUED','progress':0.0,'source_asset_id':source_asset_id,'payload':payload or {}})
    def update(self,job_id:str,*,status:Optional[str]=None,progress:Optional[float]=None,result:Optional[dict[str,Any]]=None,error:Optional[BaseException]=None,target_asset_id:Optional[str]=None)->dict[str,Any]:
        row=self.repo.get(job_id)
        if row is None:raise KeyError(job_id)
        if status:
            if status not in VALID_JOB_STATUSES:raise ValueError(status)
            row['status']=status
        if progress is not None:row['progress']=max(0.0,min(1.0,float(progress)))
        if result is not None:row['result']=result
        if target_asset_id is not None:row['target_asset_id']=target_asset_id
        now=dt.datetime.now().astimezone().isoformat(timespec='seconds')
        if row['status']=='RUNNING' and not row.get('started_at'):row['started_at']=now
        if row['status'] in {'SUCCESS','REVIEW_REQUIRED','FAILED','CANCELLED'}:row['finished_at']=now
        if error is not None:
            row['status']='FAILED';row['error_type']=type(error).__name__;row['error_message']=str(error);row['finished_at']=now
        self.repo.create(row)
        return self.repo.get(job_id)
    def list(self,**filters):return self.repo.list(**filters)
    def get(self,job_id:str):return self.repo.get(job_id)
