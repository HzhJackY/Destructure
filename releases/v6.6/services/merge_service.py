from __future__ import annotations
import datetime as dt
import json
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

    def _source_aware_metadata(self, record: dict[str, Any], table_family: str,
                               supplied: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Restore Family identity for both new and pre-hotfix guided Captures."""
        from table_merge import infer_capture_metadata

        run_dir = Path(record["run_path"])
        meta = {**infer_capture_metadata(run_dir), **dict(supplied or {})}
        persisted_path = run_dir / "capture_metadata.json"
        if persisted_path.exists():
            try:
                persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                persisted = {}
            # Explicit caller metadata remains authoritative, followed by the
            # persisted Capture provenance and finally safe fallbacks.
            for field in (
                "table_family", "member_table", "member_table_role",
                "source_table_title", "note_reference", "source_pdf_path", "member_table_order",
            ):
                if not meta.get(field) and persisted.get(field):
                    meta[field] = persisted[field]

        # Pre-hotfix guided Captures kept member identity in their immutable Job
        # payload.  Reconstruct it once at merge creation; never alter machine
        # table evidence to do so.
        job_payload: dict[str, Any] = {}
        with self.registry.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM jobs WHERE target_asset_id=? "
                "ORDER BY updated_at DESC, created_at DESC LIMIT 1",
                (str(record["capture_id"]),),
            ).fetchone()
            if row:
                job_payload = json.loads(row["payload_json"] or "{}")
            plan_id = str(job_payload.get("capture_plan_id") or "")
            if plan_id and not meta.get("source_table_title"):
                plan_row = conn.execute(
                    "SELECT payload_json FROM capture_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()
                if plan_row:
                    plan_payload = json.loads(plan_row["payload_json"] or "{}")
                    meta["source_table_title"] = (
                        (plan_payload.get("anchor") or {}).get("source_table_title") or ""
                    )

        family_from_job = (job_payload.get("family") or {}).get("display_name")
        options = dict(job_payload.get("options") or {})
        meta["table_family"] = str(meta.get("table_family") or family_from_job or table_family).strip()
        meta["member_table"] = str(
            meta.get("member_table") or job_payload.get("plan_member_table")
            or options.get("member_table") or meta.get("table_query") or ""
        ).strip()
        meta["member_table_role"] = str(
            meta.get("member_table_role") or options.get("member_table_role")
            or job_payload.get("target_role") or "COMPONENT"
        ).strip()
        meta["source_table_title"] = str(
            meta.get("source_table_title") or options.get("source_table_title")
            or meta.get("member_table") or ""
        ).strip()
        meta["note_reference"] = str(
            meta.get("note_reference") or options.get("note_reference")
            or options.get("note_number") or meta.get("note_number") or ""
        ).strip()
        meta["source_pdf"] = str(meta.get("source_pdf_path") or record.get("pdf_id") or meta.get("pdf_name") or "")
        meta["member_table_order"] = meta.get("member_table_order") or options.get("member_table_order")
        return meta
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
        from capture_library import capture_readiness
        blocked=[]
        for record in records:
            result_path=Path(record['run_path'])/'table_capture_result.json'
            if not result_path.exists():
                blocked.append({'capture_id':record['capture_id'],'blockers':['MISSING_CAPTURE_EVIDENCE']})
                continue
            try:
                result=json.loads(result_path.read_text(encoding='utf-8'))
                readiness=capture_readiness(result)
            except (OSError,json.JSONDecodeError,ValueError,TypeError) as exc:
                blocked.append({'capture_id':record['capture_id'],'blockers':[f'INVALID_CAPTURE_EVIDENCE:{type(exc).__name__}']})
                continue
            if str(record.get('lifecycle_status') or 'ACTIVE')!='ACTIVE':
                readiness['merge_blockers'].append(f"LIFECYCLE:{record.get('lifecycle_status')}")
            if not readiness['merge_ready'] or str(record.get('lifecycle_status') or 'ACTIVE')!='ACTIVE':
                blocked.append({'capture_id':record['capture_id'],'blockers':readiness['merge_blockers']})
        if blocked:
            raise ValueError(f'CAPTURE_NOT_MERGE_READY: {blocked}')
        dirs=[Path(r['run_path']) for r in records]
        supplied_by_id = {
            str(row.get("capture_run_id") or row.get("capture_id") or ""): row
            for row in (metadata_rows or [])
        }
        metadata_rows=[
            self._source_aware_metadata(
                record, str(table_id), supplied_by_id.get(str(record["capture_id"]))
            )
            for record in records
        ]
        if output_dir is None:
            stamp=dt.datetime.now().strftime('%Y%m%dT%H%M%S_%f')
            output_dir=self.paths['table_merges']/f'{str(table_id)[:70]}__{stamp}'
        taxonomy_path=Path(taxonomy_path or self.paths['taxonomy'])
        artifacts=create_merge_project(dirs,metadata_rows,Path(output_dir),table_id,taxonomy_path,reference_capture_run_id=reference_capture_id)
        ensure_merge_metadata(Path(output_dir))
        sync=sync_merge_run(Path(output_dir))
        if sync.get("status")!="OK":
            raise RuntimeError(f"MERGE_REGISTRY_SYNC_FAILED: {sync}")
        return {'merge_id':Path(output_dir).name,'run_path':str(output_dir),'artifacts':artifacts}
    def refresh(self,merge_id:str,*,persist_taxonomy:bool=False)->dict[str,Any]:
        from table_merge import refresh_merge_project
        row=next((x for x in self.repo.list(include_trash=False) if str(x.get('merge_id'))==str(merge_id)),None)
        if row is None:raise KeyError(merge_id)
        artifacts=refresh_merge_project(Path(row['run_path']),persist_taxonomy=persist_taxonomy)
        sync=sync_merge_run(Path(row['run_path']))
        if sync.get("status")!="OK":
            raise RuntimeError(f"MERGE_REGISTRY_SYNC_FAILED: {sync}")
        return artifacts
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
