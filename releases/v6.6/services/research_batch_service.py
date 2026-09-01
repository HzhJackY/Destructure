"""Persistent parent-batch governance for guided research capture."""
from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def now(): return datetime.now(timezone.utc).isoformat()

class ResearchBatchService:
    def __init__(self, registry, *, asset_service=None):
        self.registry=registry
        self.asset_service=asset_service
    def create(self, display_name:str, table_family:str, payload:dict[str,Any]|None=None)->dict[str,Any]:
        item={'research_batch_id':'RB_'+uuid.uuid4().hex,'display_name':display_name,'table_family':table_family,'status':'ACTIVE','payload':payload or {},'created_at':now()}
        with self.registry.connect() as c:
            c.execute('INSERT INTO research_batches(research_batch_id,display_name,table_family,status,payload_json,created_at,updated_at,archived) VALUES(?,?,?,?,?,?,?,0)',(item['research_batch_id'],display_name,table_family,'ACTIVE',json.dumps(item['payload'],ensure_ascii=False),item['created_at'],item['created_at']))
        return item
    def attach(self, research_batch_id:str, *, plan_id:str|None=None, source_batch_id:str|None=None, role:str='SOURCE')->None:
        with self.registry.connect() as c: c.execute('INSERT OR IGNORE INTO research_batch_members(research_batch_id,plan_id,source_batch_id,role,status,created_at) VALUES(?,?,?,?,?,?)',(research_batch_id,plan_id,source_batch_id,role,'ACTIVE',now()))
    def transition(self, research_batch_id:str,status:str)->None:
        if status not in {'ACTIVE','TRASHED','INVALIDATED','ARCHIVED'}: raise ValueError(status)
        with self.registry.connect() as c:
            c.execute('UPDATE research_batches SET status=?,archived=?,updated_at=? WHERE research_batch_id=?',(status,int(status in {'TRASHED','ARCHIVED'}),now(),research_batch_id));c.execute('UPDATE research_batch_members SET status=? WHERE research_batch_id=?',(status,research_batch_id))
            members=[dict(x) for x in c.execute('SELECT plan_id,source_batch_id FROM research_batch_members WHERE research_batch_id=?',(research_batch_id,))]
            for m in members:
                if m.get('plan_id'):
                    if status == 'ACTIVE':
                        plan_row=c.execute('SELECT payload_json FROM capture_plans WHERE plan_id=?',(m['plan_id'],)).fetchone()
                        payload=json.loads(plan_row['payload_json'] or '{}') if plan_row else {}
                        restored=payload.get('plan_status') if payload.get('plan_status') in {'CERTIFIED','REVIEW_REQUIRED'} else 'CERTIFIED'
                        c.execute('UPDATE capture_plans SET status=?,archived=0 WHERE plan_id=?',(restored,m['plan_id']))
                    else:
                        c.execute('UPDATE capture_plans SET status=?,archived=? WHERE plan_id=?',(status,int(status=='TRASHED'),m['plan_id']))
                if m.get('source_batch_id') and status=='TRASHED': c.execute("UPDATE jobs SET status='CANCELLED' WHERE batch_id=? AND status IN ('QUEUED','RUNNING')",(m['source_batch_id'],))
        self.registry.event('RESEARCH_BATCH_'+status,asset_type='RESEARCH_BATCH',asset_id=research_batch_id,payload={'status':status})
    def impact(self, research_batch_id:str)->dict[str,Any]:
        with self.registry.connect() as c:
            members=[dict(x) for x in c.execute('SELECT * FROM research_batch_members WHERE research_batch_id=?',(research_batch_id,))]
            plans=[x['plan_id'] for x in members if x.get('plan_id')]; batches=[x['source_batch_id'] for x in members if x.get('source_batch_id')]
            jobs=sum(c.execute('SELECT COUNT(*) FROM jobs WHERE batch_id=?',(x,)).fetchone()[0] for x in batches)
            captures=sum(c.execute('SELECT COUNT(*) FROM captures WHERE batch_id=?',(x,)).fetchone()[0] for x in batches)
        return {'research_batch_id':research_batch_id,'plans':len(plans),'source_batches':len(batches),'jobs':jobs,'captures':captures,'members':members}
    def trash(self,research_batch_id:str)->dict[str,Any]:
        impact=self.impact(research_batch_id)
        capture_ids=self.all_capture_ids(research_batch_id)
        asset_result=self.asset_service.trash(capture_ids) if self.asset_service and capture_ids else {'trashed': []}
        self.transition(research_batch_id,'TRASHED')
        return impact|{'status':'TRASHED','capture_lifecycle':asset_result}
    def restore(self,research_batch_id:str)->dict[str,Any]:
        impact=self.impact(research_batch_id)
        capture_ids=self.all_capture_ids(research_batch_id)
        asset_result=self.asset_service.restore(capture_ids) if self.asset_service and capture_ids else {'restored': []}
        self.transition(research_batch_id,'ACTIVE')
        return impact|{'status':'ACTIVE','capture_lifecycle':asset_result}
    def rerun_candidates(self,research_batch_id:str, mode:str='REVIEW_REQUIRED')->list[dict[str,Any]]:
        """Return only plan members eligible for a versioned rerun; execution is
        delegated to GuidedCaptureService so target constraints are preserved."""
        result_index={(row['plan_id'], row['member_table']): row for row in self.result_review(research_batch_id)}
        rows=[]
        for plan in self.plan_view(research_batch_id):
            for item in plan['items']:
                if item.get('member_table_role')!='NOTE_DETAIL': continue
                payload=json.loads(item.get('payload_json') or '{}')
                target=payload.get('certified_note_target') or {}
                review=result_index.get((plan['plan_id'], item.get('member_table')), {})
                requires_rerun=(
                    review.get('capture_quality') == 'REVIEW_REQUIRED'
                    or review.get('execution_status') == 'FAILED'
                )
                if mode=='ALL' or (mode=='REVIEW_REQUIRED' and requires_rerun):
                    if target.get('status')=='CERTIFIED_NOTE_TARGET': rows.append({'plan_id':plan['plan_id'],'member_table':item.get('member_table'),'target':target,'rerun_mode':mode})
        return rows
    def build_rerun_plans(self,research_batch_id:str, mode:str='REVIEW_REQUIRED')->list[dict[str,Any]]:
        """Persist executable, versioned rerun plans from certified targets.

        This is deliberately separate from ``retry_failed``: REVIEW_REQUIRED
        is a completed Capture needing a new controlled attempt, not a failed
        worker job.
        """
        from discovery_registry import DiscoveryRegistry
        wanted={(x['plan_id'], x['member_table']) for x in self.rerun_candidates(research_batch_id, mode)}
        out=[]
        store=DiscoveryRegistry(self.registry)
        for plan in self.plan_view(research_batch_id):
            payload=dict(plan.get('payload') or {})
            items=list(payload.get('items') or [])
            chosen=[item for item in items if item.get('member_table_role') == 'NOTE_DETAIL' and (plan['plan_id'], item.get('member_table')) in wanted]
            if not chosen:
                continue
            anchor=[item for item in items if item.get('member_table_role') == 'STATEMENT_ANCHOR']
            rerun=dict(payload)
            rerun['plan_id']='PLAN_RERUN_'+uuid.uuid4().hex
            rerun['items']=anchor+chosen
            rerun['plan_status']='CERTIFIED'
            rerun['rerun_of_plan_id']=plan['plan_id']
            rerun['rerun_mode']=mode
            rerun['status']='CERTIFIED'
            stored=store.save_capture_plan(rerun)
            self.attach(research_batch_id,plan_id=stored['plan_id'],role='PLAN')
            out.append(stored)
        return out
    def list(self)->list[dict[str,Any]]:
        with self.registry.connect() as c: rows=c.execute('SELECT * FROM research_batches ORDER BY created_at DESC').fetchall()
        return [dict(x)|{'payload':json.loads(x['payload_json'] or '{}')} for x in rows]
    def plan_view(self,research_batch_id:str)->list[dict[str,Any]]:
        with self.registry.connect() as c:
            rows=c.execute('''SELECT p.plan_id,p.pdf_id,p.table_family,p.status,p.anchor_occurrence_id,p.payload_json
              FROM capture_plans p JOIN research_batch_members m ON m.plan_id=p.plan_id
              WHERE m.research_batch_id=? AND m.role='PLAN' ORDER BY p.created_at''',(research_batch_id,)).fetchall()
            out=[]
            for row in rows:
                p=dict(row); p['payload']=json.loads(p.pop('payload_json') or '{}')
                p['items']=[dict(x) for x in c.execute('SELECT * FROM capture_plan_items WHERE plan_id=? ORDER BY capture_order',(p['plan_id'],))]
                out.append(p)
        return out
    def capture_ids(self,research_batch_id:str)->list[str]:
        with self.registry.connect() as c:
            rows=c.execute('''SELECT DISTINCT c.capture_id FROM captures c JOIN research_batch_members m
              ON m.source_batch_id=c.batch_id WHERE m.research_batch_id=? AND m.status='ACTIVE'
              AND c.lifecycle_status='ACTIVE' AND c.merge_ready=1''',(research_batch_id,)).fetchall()
        return [str(x['capture_id']) for x in rows]
    def all_capture_ids(self,research_batch_id:str)->list[str]:
        """Return linked captures irrespective of lifecycle for reversible batch actions."""
        with self.registry.connect() as c:
            rows=c.execute('''SELECT DISTINCT c.capture_id FROM captures c JOIN research_batch_members m
              ON m.source_batch_id=c.batch_id WHERE m.research_batch_id=?''',(research_batch_id,)).fetchall()
        return [str(x['capture_id']) for x in rows]
    def result_review(self,research_batch_id:str)->list[dict[str,Any]]:
        """Project the latest non-superseded Capture attempt for each member.

        Job status is immutable execution history.  Current Capture quality is
        derived independently from the latest Capture evidence, so an older
        REVIEW_REQUIRED attempt cannot contaminate a newer hard-boundary result.
        """
        from capture_library import capture_readiness

        plans=self.plan_view(research_batch_id); out=[]
        with self.registry.connect() as c:
            raw_jobs=[dict(row) for row in c.execute('''SELECT j.job_id,j.status,j.target_asset_id,
                  j.result_json,j.payload_json,j.created_at,j.updated_at
                  FROM jobs j JOIN research_batch_members rb ON rb.source_batch_id=j.batch_id
                  WHERE rb.research_batch_id=?''',(research_batch_id,)).fetchall()]
            capture_rows={
                str(row['capture_id']):dict(row)
                for row in c.execute('''SELECT capture_id,run_path,lifecycle_status,boundary_status,
                    header_dimension_status,merge_ready FROM captures''').fetchall()
            }

        indexed={}
        for job in raw_jobs:
            payload=json.loads(job.get('payload_json') or '{}')
            key=(str(payload.get('capture_plan_id') or ''),str(payload.get('plan_member_table') or ''))
            indexed.setdefault(key,[]).append(job)

        # A rerun plan supersedes an earlier member only after it has produced
        # an active, merge-ready Capture. Merely creating/enqueuing a rerun must
        # not make the last usable result disappear.
        superseded_members=set()
        for candidate in plans:
            original=(candidate.get('payload') or {}).get('rerun_of_plan_id')
            if not original:
                continue
            for member in candidate.get('items') or []:
                if member.get('member_table_role')!='NOTE_DETAIL':
                    continue
                member_name=str(member.get('member_table') or '')
                attempts=sorted(
                    indexed.get((str(candidate['plan_id']),member_name),[]),
                    key=lambda row:str(row.get('updated_at') or row.get('created_at') or row.get('job_id') or ''),
                )
                latest_attempt=attempts[-1] if attempts else None
                capture=capture_rows.get(str((latest_attempt or {}).get('target_asset_id') or ''))
                if (
                    latest_attempt
                    and latest_attempt.get('status')=='SUCCESS'
                    and capture
                    and str(capture.get('lifecycle_status') or '')=='ACTIVE'
                    and bool(capture.get('merge_ready'))
                ):
                    superseded_members.add((str(original),member_name))

        for plan in plans:
            for item in plan['items']:
                if item.get('member_table_role')!='NOTE_DETAIL':
                    continue
                member_table=str(item.get('member_table') or '')
                if (str(plan['plan_id']),member_table) in superseded_members:
                    continue
                jobs=sorted(
                    indexed.get((str(plan['plan_id']),member_table),[]),
                    key=lambda row:str(row.get('updated_at') or row.get('created_at') or row.get('job_id') or ''),
                )
                latest=jobs[-1] if jobs else None
                latest_capture_id=str((latest or {}).get('target_asset_id') or '')
                latest_capture=capture_rows.get(latest_capture_id)
                readiness=None
                if latest_capture:
                    run_path=Path(str(latest_capture.get('run_path') or ''))
                    result_path=run_path/'table_capture_result.json'
                    if result_path.exists():
                        try:
                            result=json.loads(result_path.read_text(encoding='utf-8'))
                            readiness=capture_readiness(result)
                        except (OSError,json.JSONDecodeError,ValueError,TypeError):
                            readiness=None

                if readiness:
                    capture_quality=str(readiness['capture_quality_status'])
                    blockers=list(readiness['merge_blockers'])
                    boundary_status=readiness['boundary_status']
                    header_status=readiness['header_dimension_status']
                    if str(latest_capture.get('lifecycle_status') or '')!='ACTIVE':
                        capture_quality='REVIEW_REQUIRED'
                        blockers.append(f"LIFECYCLE:{latest_capture.get('lifecycle_status')}")
                elif latest_capture:
                    capture_quality='READY' if bool(latest_capture.get('merge_ready')) else 'REVIEW_REQUIRED'
                    blockers=[] if capture_quality=='READY' else ['CAPTURE_REGISTRY_NOT_READY']
                    boundary_status=latest_capture.get('boundary_status')
                    header_status=latest_capture.get('header_dimension_status')
                elif latest:
                    capture_quality='REVIEW_REQUIRED'
                    blockers=[
                        'CAPTURE_ASSET_MISSING'
                        if latest.get('status')=='SUCCESS'
                        else f"EXECUTION:{latest.get('status')}"
                    ]
                    boundary_status=None;header_status=None
                else:
                    capture_quality='PENDING'
                    blockers=[]
                    boundary_status=None;header_status=None

                target=json.loads(item.get('payload_json') or '{}').get('certified_note_target') or {}
                out.append({
                    'plan_id':plan['plan_id'],
                    'member_table':member_table,
                    'note_reference':item.get('note_reference'),
                    'source_pdf':plan.get('pdf_id'),
                    'execution_status':(latest or {}).get('status') or 'NOT_SUBMITTED',
                    'execution_history':','.join(str(job.get('status') or '') for job in jobs),
                    'target_status':target.get('status','NOTE_TARGET_UNRESOLVED'),
                    'target_heading':target.get('target_heading'),
                    'capture_quality':capture_quality,
                    'quality_blockers':blockers,
                    'boundary_status':boundary_status,
                    'header_dimension_status':header_status,
                    'job_count':len(jobs),
                    'capture_ids':[latest_capture_id] if latest_capture_id else [],
                    'attempt_capture_ids':[str(job.get('target_asset_id')) for job in jobs if job.get('target_asset_id')],
                })
        return out
