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


MERGE_EXCLUDED_DERIVED_STATUSES = frozenset({
    "DERIVED_REJECTED_NON_BLOCKING",
    "SUPPRESSED_BY_EXPLICIT_TOTAL",
})


class MergeService:
    """Headless Merge/Taxonomy project façade."""
    def __init__(self,repo:MergeRepository,capture_repo:CaptureRepository,registry:MetadataRegistry,synchronizer:RegistrySynchronizer,paths:dict[str,Path],eligibility_service=None):
        self.repo=repo;self.capture_repo=capture_repo;self.registry=registry;self.synchronizer=synchronizer;self.paths={k:Path(v) for k,v in paths.items()};self.eligibility_service=eligibility_service
    def list(self,*,include_trash:bool=False,only_trash:bool=False):return self.repo.list(include_trash=include_trash,only_trash=only_trash)

    @staticmethod
    def _read_capture_json(record: dict[str, Any], filename: str) -> dict[str, Any]:
        path = Path(record["run_path"]) / filename
        if not path.is_file():
            raise ValueError(f"MISSING_CAPTURE_EVIDENCE:{record['capture_id']}:{filename}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError(
                f"INVALID_CAPTURE_EVIDENCE:{record['capture_id']}:{filename}:{type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict):
            raise ValueError(f"INVALID_CAPTURE_EVIDENCE:{record['capture_id']}:{filename}:NOT_OBJECT")
        return payload

    def _bundle_membership(self, capture_id: str) -> Optional[dict[str, Any]]:
        with self.registry.connect() as conn:
            rows = conn.execute(
                """SELECT cbc.bundle_id,cbc.block_id,cbc.logical_asset_id,
                          cbc.child_order,cbc.status AS child_status,
                          cb.status AS bundle_status,cb.container_id AS bundle_container_id,
                          cb.table_family_id AS bundle_table_family_id,
                          cb.member_table_id AS bundle_member_table_id,
                          nc.source_pdf_id AS bundle_source_pdf_id,
                          nc.source_pdf_sha256 AS bundle_source_pdf_sha256
                   FROM capture_bundle_children cbc
                   JOIN capture_bundles cb ON cb.bundle_id=cbc.bundle_id
                   LEFT JOIN note_containers nc ON nc.container_id=cb.container_id
                   WHERE cbc.capture_id=? AND cbc.status<>'SUPERSEDED'
                   ORDER BY cbc.bundle_id,cbc.child_order,cbc.block_id""",
                (str(capture_id),),
            ).fetchall()
        if len(rows) > 1:
            raise ValueError(f"CAPTURE_MULTIPLE_ACTIVE_BUNDLES:{capture_id}")
        return dict(rows[0]) if rows else None

    def _bundle_children(self, bundle_id: str) -> list[dict[str, Any]]:
        with self.registry.connect() as conn:
            rows = conn.execute(
                """SELECT cbc.bundle_id,cbc.block_id,cbc.capture_id,
                          cbc.logical_asset_id,cbc.child_order,
                          cbc.status AS child_status,cb.status AS bundle_status,
                          cb.container_id AS bundle_container_id,
                          cb.table_family_id AS bundle_table_family_id,
                          cb.member_table_id AS bundle_member_table_id,
                          nc.source_pdf_id AS bundle_source_pdf_id,
                          nc.source_pdf_sha256 AS bundle_source_pdf_sha256
                   FROM capture_bundle_children cbc
                   JOIN capture_bundles cb ON cb.bundle_id=cbc.bundle_id
                   LEFT JOIN note_containers nc ON nc.container_id=cb.container_id
                   WHERE cbc.bundle_id=? AND cbc.status<>'SUPERSEDED'
                   ORDER BY cbc.child_order,cbc.block_id,cbc.capture_id""",
                (str(bundle_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def _registry_pdf_sha256(self, record: dict[str, Any]) -> str:
        pdf_id = str(record.get("pdf_id") or "").strip()
        if not pdf_id:
            return ""
        with self.registry.connect() as conn:
            row = conn.execute(
                "SELECT sha256 FROM pdf_assets WHERE pdf_id=?", (pdf_id,)
            ).fetchone()
        return str(row["sha256"] if row and row["sha256"] else "").strip()

    def _bundle_target_identity(
        self,
        record: dict[str, Any],
        capture_metadata: dict[str, Any],
        result: dict[str, Any],
        source_metadata: dict[str, Any],
        child_row: dict[str, Any],
    ) -> dict[str, str]:
        certified_target = dict(capture_metadata.get("certified_target") or {})
        graph_family_id = str(child_row.get("bundle_table_family_id") or "").strip()
        graph_member_id = str(child_row.get("bundle_member_table_id") or "").strip()
        metadata_family_id = str(
            capture_metadata.get("table_family_id")
            or capture_metadata.get("table_family")
            or ""
        ).strip()
        metadata_member_id = str(
            certified_target.get("member_table_id")
            or capture_metadata.get("member_table")
            or ""
        ).strip()
        certified_logical_table_id = str(
            certified_target.get("logical_table_id") or ""
        ).strip()
        bundle_pdf_sha256 = str(
            child_row.get("bundle_source_pdf_sha256") or ""
        ).strip()
        bundle_pdf_id = str(child_row.get("bundle_source_pdf_id") or "").strip()
        record_pdf_id = str(record.get("pdf_id") or "").strip()
        asset_pdf_sha256 = self._registry_pdf_sha256(record)
        result_pdf_sha256 = str(result.get("pdf_sha256") or "").strip()
        if graph_family_id != metadata_family_id:
            raise ValueError(
                f"CAPTURE_BUNDLE_TABLE_FAMILY_MISMATCH:{record['capture_id']}:"
                f"{graph_family_id}:{metadata_family_id}"
            )
        if graph_member_id != metadata_member_id:
            raise ValueError(
                f"CAPTURE_BUNDLE_MEMBER_TABLE_MISMATCH:{record['capture_id']}:"
                f"{graph_member_id}:{metadata_member_id}"
            )
        if not bundle_pdf_sha256:
            raise ValueError(
                f"CAPTURE_BUNDLE_PDF_SHA_MISSING:{record['capture_id']}:"
                f"{child_row.get('bundle_container_id')}"
            )
        if not bundle_pdf_id or record_pdf_id != bundle_pdf_id:
            raise ValueError(
                f"CAPTURE_BUNDLE_PDF_ID_MISMATCH:{record['capture_id']}:"
                f"{record_pdf_id}:{bundle_pdf_id}"
            )
        if asset_pdf_sha256 and asset_pdf_sha256 != bundle_pdf_sha256:
            raise ValueError(
                f"CAPTURE_REGISTRY_PDF_SHA_MISMATCH:{record['capture_id']}:"
                f"{asset_pdf_sha256}:{bundle_pdf_sha256}"
            )
        if bundle_pdf_sha256 != result_pdf_sha256:
            raise ValueError(
                f"CAPTURE_BUNDLE_PDF_SHA_MISMATCH:{record['capture_id']}:"
                f"{bundle_pdf_sha256}:{result_pdf_sha256}"
            )
        identity = {
            "source_pdf_sha256": bundle_pdf_sha256,
            "source_pdf_id": bundle_pdf_id,
            "table_family_id": graph_family_id,
            "member_table_id": graph_member_id,
            "certified_logical_table_id": certified_logical_table_id,
            "member_table_role": str(source_metadata.get("member_table_role") or "").strip(),
            "note_reference": str(source_metadata.get("note_reference") or "").strip(),
            "company": str(record.get("company") or "").strip(),
            "document_year": str(record.get("document_year") or "").strip(),
        }
        missing = [
            field for field in (
                "source_pdf_sha256", "table_family_id", "member_table_id",
                "certified_logical_table_id"
            ) if not identity[field]
        ]
        if missing:
            raise ValueError(
                f"CAPTURE_BUNDLE_TARGET_IDENTITY_MISSING:{record['capture_id']}:{missing}"
            )
        return identity

    @staticmethod
    def _validated_physical_block_id(
        record: dict[str, Any],
        capture_metadata: dict[str, Any],
        result: dict[str, Any],
        graph_block_id: str,
        *,
        require_result_rows: bool = False,
    ) -> str:
        metadata_block_id = str(
            capture_metadata.get("table_block_id")
            or capture_metadata.get("block_id")
            or ""
        ).strip()
        result_rows = list(result.get("rows") or [])
        row_block_values = [
            str(row.get("table_block_id") or "").strip()
            for row in result_rows
        ]
        row_block_ids = {value for value in row_block_values if value}
        sole_result_block_id = next(iter(row_block_ids)) if len(row_block_ids) == 1 else ""
        expected = str(
            graph_block_id or metadata_block_id or sole_result_block_id or ""
        ).strip()
        if not expected or metadata_block_id != expected:
            raise ValueError(
                f"CAPTURE_BUNDLE_BLOCK_LINEAGE_MISMATCH:{record['capture_id']}:"
                f"{expected}:{metadata_block_id}"
            )
        if require_result_rows and (
            not result_rows or any(not value for value in row_block_values)
        ):
            raise ValueError(
                f"CAPTURE_RESULT_BLOCK_LINEAGE_MISSING:{record['capture_id']}:{expected}"
            )
        if row_block_ids and row_block_ids != {expected}:
            raise ValueError(
                f"CAPTURE_RESULT_BLOCK_LINEAGE_MISMATCH:{record['capture_id']}:"
                f"{expected}:{sorted(row_block_ids)}"
            )
        return expected

    @staticmethod
    def _merge_row_exclusions(
        record: dict[str, Any],
        result: dict[str, Any],
        block_id: str,
    ) -> list[dict[str, Any]]:
        exclusions: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for row in result.get("rows") or []:
            derived_status = str(row.get("derived_status") or "").strip()
            if derived_status not in MERGE_EXCLUDED_DERIVED_STATUSES:
                continue
            observation_type = str(row.get("observation_type") or "").strip()
            if observation_type != "DERIVED_OBSERVATION":
                raise ValueError(
                    f"MERGE_ROW_EXCLUSION_SOURCE_STATUS_CONFLICT:"
                    f"{record['capture_id']}:{row.get('row_order')}:"
                    f"{observation_type}:{derived_status}"
                )
            try:
                row_order = int(row["row_order"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"MERGE_ROW_EXCLUSION_ROW_ORDER_INVALID:{record['capture_id']}"
                ) from exc
            for cell in row.get("cells") or []:
                if str(cell.get("cell_role") or "") != "NUMERIC":
                    continue
                try:
                    column_ordinal = int(cell["column_ordinal"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"MERGE_ROW_EXCLUSION_COLUMN_INVALID:{record['capture_id']}:{row_order}"
                    ) from exc
                key = (block_id, row_order, column_ordinal)
                if key in seen:
                    raise ValueError(
                        f"DUPLICATE_MERGE_ROW_EXCLUSION:{record['capture_id']}:{key}"
                    )
                seen.add(key)
                exclusions.append({
                    "capture_run_id": str(record["capture_id"]),
                    "table_block_id": block_id,
                    "row_order": row_order,
                    "column_ordinal": column_ordinal,
                    "normalized_item": str(row.get("normalized_item") or row.get("item") or ""),
                    "derived_status": derived_status,
                    "observation_type": observation_type,
                    "derivation_method": str(row.get("derivation_method") or ""),
                    "value_raw": cell.get("raw"),
                    "parsed_number": cell.get("parsed_number"),
                    "value_yuan": cell.get("value_yuan"),
                })
        return exclusions

    def _expand_bundle_sources(
        self,
        requested_records: list[dict[str, Any]],
        *,
        table_id: str,
        supplied_by_id: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        selected_bundles: set[str] = set()
        all_exclusions: list[dict[str, Any]] = []

        for requested_record in requested_records:
            requested_id = str(requested_record["capture_id"])
            membership = self._bundle_membership(requested_id)
            if membership is None:
                child_rows = [{
                    "bundle_id": "",
                    "block_id": "",
                    "capture_id": requested_id,
                    "child_order": 0,
                    "child_status": "UNBUNDLED",
                    "bundle_status": "UNBUNDLED",
                    "bundle_container_id": None,
                    "bundle_table_family_id": None,
                    "bundle_member_table_id": None,
                    "bundle_source_pdf_sha256": None,
                    "bundle_source_pdf_id": None,
                    "logical_asset_id": None,
                }]
                child_records = [requested_record]
            else:
                bundle_id = str(membership["bundle_id"])
                if bundle_id in selected_bundles:
                    raise ValueError(f"DUPLICATE_CAPTURE_BUNDLE_INPUT:{bundle_id}")
                child_rows = self._bundle_children(bundle_id)
                if not child_rows:
                    raise ValueError(f"EMPTY_CAPTURE_BUNDLE:{bundle_id}")
                child_orders = [
                    int(row.get("child_order")) for row in child_rows
                ]
                root_rows = [
                    row for row in child_rows
                    if int(row.get("child_order")) == 0
                ]
                if len(root_rows) != 1:
                    raise ValueError(
                        f"CAPTURE_BUNDLE_ROOT_CARDINALITY_INVALID:{bundle_id}:"
                        f"{child_orders}"
                    )
                if (
                    any(order < 0 for order in child_orders)
                    or len(set(child_orders)) != len(child_orders)
                    or sorted(child_orders) != list(range(len(child_orders)))
                ):
                    raise ValueError(
                        f"CAPTURE_BUNDLE_CHILD_ORDER_INVALID:{bundle_id}:"
                        f"{child_orders}"
                    )
                root_row = root_rows[0]
                if str(root_row.get("capture_id") or "") != requested_id:
                    raise ValueError(
                        f"CAPTURE_BUNDLE_ROOT_REQUIRED:{requested_id}:{bundle_id}:"
                        f"{root_row.get('capture_id')}"
                    )
                child_ids = [str(row.get("capture_id") or "") for row in child_rows]
                if any(not capture_id for capture_id in child_ids):
                    raise ValueError(f"CAPTURE_BUNDLE_CHILD_ID_MISSING:{bundle_id}")
                if len(child_ids) != len(set(child_ids)):
                    raise ValueError(f"DUPLICATE_CAPTURE_BUNDLE_CHILD:{bundle_id}")
                unordered_child_records = self.capture_repo.get_many(child_ids)
                child_records_by_id = {
                    str(record["capture_id"]): record for record in unordered_child_records
                }
                if len(child_records_by_id) != len(unordered_child_records):
                    raise ValueError(f"DUPLICATE_CAPTURE_REPOSITORY_RECORD:{bundle_id}")
                if len(child_records_by_id) != len(child_ids):
                    found = set(child_records_by_id)
                    missing = [capture_id for capture_id in child_ids if capture_id not in found]
                    raise KeyError(f"Missing Capture IDs: {missing}")
                child_records = [child_records_by_id[capture_id] for capture_id in child_ids]
                selected_bundles.add(bundle_id)

            root_target: Optional[dict[str, str]] = None
            for child_row, record in zip(child_rows, child_records):
                capture_id = str(record["capture_id"])
                if capture_id in selected_ids:
                    raise ValueError(f"DUPLICATE_MERGE_CAPTURE_SOURCE:{capture_id}")
                capture_metadata = self._read_capture_json(record, "capture_metadata.json")
                result = self._read_capture_json(record, "table_capture_result.json")
                persisted_bundle_id = str(capture_metadata.get("capture_bundle_id") or "")
                graph_bundle_id = str(child_row.get("bundle_id") or "")
                if graph_bundle_id and persisted_bundle_id != graph_bundle_id:
                    raise ValueError(
                        f"CAPTURE_BUNDLE_LINEAGE_MISMATCH:{capture_id}:"
                        f"{persisted_bundle_id}:{graph_bundle_id}"
                    )
                if not graph_bundle_id and persisted_bundle_id:
                    raise ValueError(
                        f"CAPTURE_BUNDLE_REGISTRY_GRAPH_MISSING:{capture_id}:"
                        f"{persisted_bundle_id}"
                    )
                if graph_bundle_id and str(child_row.get("bundle_status") or "") != "READY":
                    raise ValueError(
                        f"CAPTURE_BUNDLE_NOT_READY:{graph_bundle_id}:"
                        f"{child_row.get('bundle_status')}"
                    )
                if graph_bundle_id and str(child_row.get("child_status") or "") != "CAPTURED":
                    raise ValueError(
                        f"CAPTURE_BUNDLE_CHILD_NOT_CAPTURED:{capture_id}:"
                        f"{child_row.get('child_status')}"
                    )
                persisted_source_metadata = self._source_aware_metadata(
                    record, str(table_id)
                )
                has_row_exclusions = any(
                    str(row.get("derived_status") or "")
                    in MERGE_EXCLUDED_DERIVED_STATUSES
                    for row in (result.get("rows") or [])
                )
                if graph_bundle_id or has_row_exclusions:
                    physical_block_id = self._validated_physical_block_id(
                        record, capture_metadata, result,
                        str(child_row.get("block_id") or ""),
                        require_result_rows=True,
                    )
                else:
                    physical_block_id = str(
                        capture_metadata.get("table_block_id")
                        or capture_metadata.get("block_id") or ""
                    ).strip()
                if graph_bundle_id:
                    target = self._bundle_target_identity(
                        record, capture_metadata, result,
                        persisted_source_metadata, child_row,
                    )
                else:
                    target = {
                        "source_pdf_sha256": str(result.get("pdf_sha256") or ""),
                        "table_family_id": str(
                            capture_metadata.get("table_family_id")
                            or persisted_source_metadata.get("table_family") or ""
                        ),
                        "member_table_id": str(
                            (capture_metadata.get("certified_target") or {}).get("member_table_id")
                            or persisted_source_metadata.get("member_table") or ""
                        ),
                        "certified_logical_table_id": str(
                            (capture_metadata.get("certified_target") or {}).get("logical_table_id")
                            or ""
                        ),
                    }
                if root_target is None:
                    root_target = target
                elif target != root_target:
                    raise ValueError(
                        f"CAPTURE_BUNDLE_TARGET_MISMATCH:{capture_id}:"
                        f"{target}:{root_target}"
                    )
                exclusions = self._merge_row_exclusions(
                    record, result, physical_block_id
                )
                source_metadata = self._source_aware_metadata(
                    record, str(table_id), supplied_by_id.get(capture_id)
                )
                lineage = {
                    "capture_bundle_id": graph_bundle_id or None,
                    "bundle_root_capture_id": requested_id,
                    "bundle_block_id": str(child_row.get("block_id") or "") or None,
                    "logical_asset_id": str(child_row.get("logical_asset_id") or "") or None,
                    "bundle_child_order": int(child_row.get("child_order") or 0),
                    "bundle_child_status": str(child_row.get("child_status") or ""),
                    "bundle_status": str(child_row.get("bundle_status") or ""),
                    "bundle_role": "ROOT" if capture_id == requested_id else "DERIVED",
                    "target_identity": target,
                }
                source_metadata.update({
                    "capture_bundle_id": graph_bundle_id or None,
                    "merge_bundle_lineage": lineage,
                    "merge_row_exclusions": exclusions,
                })
                selected.append({
                    "record": record,
                    "result": result,
                    "metadata": source_metadata,
                    "lineage": lineage,
                    "exclusions": exclusions,
                })
                selected_ids.add(capture_id)
                all_exclusions.extend(exclusions)

        status_counts: dict[str, int] = {}
        for exclusion in all_exclusions:
            status = str(exclusion["derived_status"])
            status_counts[status] = status_counts.get(status, 0) + 1
        selected_capture_ids = [str(item["record"]["capture_id"]) for item in selected]
        expansion = {
            "contract_version": "v6.11-capture-bundle-target-row-filter-v1",
            "requested_capture_ids": [str(record["capture_id"]) for record in requested_records],
            "bundle_graph_discovered_capture_ids": selected_capture_ids,
            "selected_capture_ids": selected_capture_ids,
            "requested_capture_count": len(requested_records),
            "bundle_graph_discovered_capture_count": len(selected),
            "selected_capture_count": len(selected),
            "capture_level_exclusion_count": 0,
            "row_cell_exclusion_count": len(all_exclusions),
            "row_cell_exclusion_status_counts": status_counts,
            "row_cell_exclusions": all_exclusions,
            "selection_policy": "SAME_CAPTURE_BUNDLE_AND_CERTIFIED_LOGICAL_TABLE_READY_MERGE_READY",
            "row_filter_policy": "EXCLUDE_NON_SOURCE_DERIVED_CELLS_FAIL_CLOSED",
        }
        return selected, expansion

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
        order_policy:Optional[str]=None,
        reference_report_year:Optional[str]=None,
    )->dict[str,Any]:
        from table_merge import create_merge_project,infer_capture_metadata
        from merge_library import ensure_merge_metadata
        ids=list(map(str,capture_ids))
        if len(ids)!=len(set(ids)):
            raise ValueError(f'DUPLICATE_CAPTURE_IDS:{ids}')
        unordered_records=self.capture_repo.get_many(ids)
        records_by_id={str(record['capture_id']):record for record in unordered_records}
        if len(records_by_id)!=len(unordered_records):
            raise ValueError('DUPLICATE_CAPTURE_REPOSITORY_RECORD')
        if len(records_by_id)!=len(ids):
            found=set(records_by_id);missing=[x for x in ids if x not in found];raise KeyError(f'Missing Capture IDs: {missing}')
        records=[records_by_id[capture_id] for capture_id in ids]
        supplied_by_id = {
            str(row.get("capture_run_id") or row.get("capture_id") or ""): row
            for row in (metadata_rows or [])
        }
        if len(supplied_by_id)!=len(metadata_rows or []):
            raise ValueError('DUPLICATE_OR_MISSING_CAPTURE_METADATA_ID')
        selected, bundle_expansion = self._expand_bundle_sources(
            records, table_id=str(table_id), supplied_by_id=supplied_by_id
        )
        records=[item['record'] for item in selected]
        ids=[str(record['capture_id']) for record in records]
        if self.eligibility_service is not None:
            self.eligibility_service.assert_capture_ids(ids)
        from capture_library import capture_readiness
        blocked=[]
        for item in selected:
            record=item['record']
            try:
                readiness=capture_readiness(item['result'])
            except (ValueError,TypeError) as exc:
                blocked.append({'capture_id':record['capture_id'],'blockers':[f'INVALID_CAPTURE_EVIDENCE:{type(exc).__name__}']})
                continue
            blockers=list(readiness.get('merge_blockers') or [])
            lifecycle=str(record.get('lifecycle_status') or 'ACTIVE')
            if lifecycle!='ACTIVE':blockers.append(f"LIFECYCLE:{lifecycle}")
            if bool(record.get('is_trashed')):blockers.append('CAPTURE_TRASHED')
            if not bool(record.get('merge_ready')):blockers.append('REGISTRY_MERGE_READY_FALSE')
            if not readiness.get('merge_ready') or blockers:
                blocked.append({'capture_id':record['capture_id'],'blockers':blockers})
        if blocked:
            raise ValueError(f'CAPTURE_NOT_MERGE_READY: {blocked}')
        dirs=[Path(r['run_path']) for r in records]
        metadata_rows=[item['metadata'] for item in selected]
        if output_dir is None:
            stamp=dt.datetime.now().strftime('%Y%m%dT%H%M%S_%f')
            output_dir=self.paths['table_merges']/f'{str(table_id)[:70]}__{stamp}'
        taxonomy_path=Path(taxonomy_path or self.paths['taxonomy'])
        member_display_map: dict[str, str] = {}
        try:
            with self.registry.connect() as conn:
                member_rows = conn.execute(
                    """SELECT member_id, display_name
                       FROM family_members
                       WHERE display_name IS NOT NULL
                         AND TRIM(display_name) <> ''"""
                ).fetchall()
            member_display_map = {
                str(row["member_id"]): str(row["display_name"])
                for row in member_rows
            }
        except Exception:
            member_display_map = {}
        artifacts=create_merge_project(
            dirs,metadata_rows,Path(output_dir),table_id,taxonomy_path,
            reference_capture_run_id=reference_capture_id,
            merge_lineage=bundle_expansion,
            member_display_map=member_display_map,
            order_policy=order_policy,
            reference_report_year=reference_report_year,
        )
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
