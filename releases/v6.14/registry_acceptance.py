"""Common fail-closed acceptance harness for Research Definition registries.

This module evaluates the existing owner-service evidence.  It does not parse
PDFs, certify discoveries, execute Capture, materialize Canonical data, or
merge tables by itself.  Execution adapters must call the established backend
service graph and submit the resulting immutable snapshot to this harness.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import csv
import json
from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping

from golden_identity import (
    load_yaml, sidecar_filename, validate_identity_source_consistency,
)


class AcceptanceStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_RUN = "NOT_RUN"
    COVERAGE_GAP = "COVERAGE_GAP"


class AcceptanceStage(str, Enum):
    CORPUS_PREFLIGHT = "CorpusPreflight"
    DISCOVERY = "DiscoveryAcceptance"
    CERTIFICATION_SNAPSHOT = "CertificationSnapshotAcceptance"
    CAPTURE = "CaptureAcceptance"
    CANONICAL = "CanonicalAcceptance"
    MERGE = "MergeAcceptance"
    UI_PARITY = "UiParityAcceptance"


@dataclass(frozen=True)
class StageResult:
    stage: AcceptanceStage
    status: AcceptanceStatus
    reason_code: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FilingAcceptanceResult:
    definition_id: str
    family: str
    company_id: str
    company_name: str
    report_year: int
    pdf_sha256: str
    stages: tuple[StageResult, ...]

    @property
    def status(self) -> AcceptanceStatus:
        statuses = {item.status for item in self.stages}
        if AcceptanceStatus.FAIL in statuses:
            return AcceptanceStatus.FAIL
        if AcceptanceStatus.BLOCKED in statuses:
            return AcceptanceStatus.BLOCKED
        if AcceptanceStatus.NOT_RUN in statuses:
            return AcceptanceStatus.NOT_RUN
        if AcceptanceStatus.COVERAGE_GAP in statuses:
            return AcceptanceStatus.COVERAGE_GAP
        return AcceptanceStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        for stage in result["stages"]:
            stage["stage"] = stage["stage"].value
            stage["status"] = stage["status"].value
        return result


@dataclass(frozen=True)
class RegistryProfile:
    definition_id: str
    family: str
    golden_filename: str
    company_dirs: dict[str, str]
    required_member_tables: tuple[str, ...]

    def filing_dir(self, corpus_root: Path, company_id: str, year: int) -> Path:
        return corpus_root / "companies" / self.company_dirs[company_id] / str(year)


PORTFOLIO_PROFILE = RegistryProfile(
    definition_id="INVESTMENT_PORTFOLIO_V2",
    family="investment_portfolio",
    golden_filename="investment_portfolio_golden.yaml",
    company_dirs={
        "PING_AN": "ping_an", "NEW_CHINA_LIFE": "new_china_life",
        "CPIC_GROUP": "cpic_group", "CHINA_LIFE": "china_life",
    },
    required_member_tables=("portfolio_by_category", "portfolio_by_measurement"),
)

FINANCIAL_PROFILE = RegistryProfile(
    definition_id="FINANCIAL_INVESTMENT_V1",
    family="financial_investment",
    golden_filename="golden_values.yaml",
    company_dirs={
        "PING_AN": "ping_an", "NEW_CHINA_LIFE": "new_china_life",
        "CPIC": "cpic", "CHINA_LIFE": "china_life",
    },
    required_member_tables=(
        "fvtpl_assets", "debt_investment", "other_debt_investment",
        "other_equity_investment",
    ),
)


COMPANY_NAMES = {
    "PING_AN": "中国平安",
    "NEW_CHINA_LIFE": "新华保险",
    "CPIC": "中国太保",
    "CPIC_GROUP": "中国太保",
    "CHINA_LIFE": "中国人寿",
    "PICC": "中国人保",
}


def _csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _is_blank_csv_value(value: Any) -> bool:
    return str(value or "").strip().lower() in {"", "nan", "none", "null"}


def _manifest_count(payload: Mapping[str, Any], key: str) -> int:
    try:
        return int(payload[key])
    except (KeyError, TypeError, ValueError):
        return -1


def validate_financial_merge_artifacts(
    merges: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate the formal V6 source/bridge/audit projections fail-closed.

    Blocking bridge rows are valid evidence when their projected value remains
    blank and the reason is preserved in the audit view.  They are not silently
    converted into source-view failures.
    """
    expected_files = {
        "original": "financial_investment_original_long.csv",
        "bridge_long": "financial_investment_standards_bridge_long.csv",
        "bridge_wide": "financial_investment_standards_bridge_wide.csv",
        "audit": "financial_investment_standards_bridge_audit.csv",
    }
    required_original = {
        "presentation_member_id", "presentation_regime",
        "member_contract_version", "source_row_ids", "view_contract",
    }
    required_bridge = {
        "analysis_bridge_group", "bridge_rule_id", "bridge_projection_status",
        "source_final_value", "final_value", "bridge_semantic_key", "view_contract",
    }
    issues: list[dict[str, Any]] = []
    merge_audits: list[dict[str, Any]] = []
    for merge in merges:
        merge_id = str(merge.get("merge_id") or "")
        run_path = Path(str(merge.get("run_path") or ""))
        local_issues: list[str] = []
        manifest_path = run_path / "merge_manifest.json"
        if not manifest_path.is_file():
            local_issues.append("MERGE_MANIFEST_MISSING")
            manifest: dict[str, Any] = {}
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = {}
                local_issues.append("MERGE_MANIFEST_INVALID_JSON")
        bridge_manifest = dict(manifest.get("financial_investment_standards_bridge") or {})
        if manifest.get("merge_schema_version") != "6.9_FINANCIAL_PRESENTATION_REGIME_DUAL_VIEW":
            local_issues.append("MERGE_SCHEMA_VERSION_NOT_V6_DUAL_VIEW")
        if manifest.get("canonical_observation_schema_version") != "6.9_PRESENTATION_MEMBER_REGIME_LINEAGE":
            local_issues.append("CANONICAL_SCHEMA_VERSION_NOT_V6_LINEAGE")
        if bridge_manifest.get("schema_version") != "FINANCIAL_INVESTMENT_STANDARDS_BRIDGE_V1":
            local_issues.append("BRIDGE_SCHEMA_VERSION_MISMATCH")
        if bridge_manifest.get("delivery_policy") != "DUAL_VIEW_SOURCE_PRESENTATION_AND_EXPLICIT_BRIDGE":
            local_issues.append("BRIDGE_DELIVERY_POLICY_MISMATCH")
        if bridge_manifest.get("no_same_period_sum") is not True:
            local_issues.append("NO_SAME_PERIOD_SUM_CONTRACT_MISSING")

        paths = {name: run_path / filename for name, filename in expected_files.items()}
        for name, path in paths.items():
            if not path.is_file():
                local_issues.append(f"{name.upper()}_ARTIFACT_MISSING")
        tables: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
        if not any(issue.endswith("ARTIFACT_MISSING") for issue in local_issues):
            for name, path in paths.items():
                try:
                    tables[name] = _csv_rows(path)
                except (OSError, csv.Error):
                    local_issues.append(f"{name.upper()}_ARTIFACT_INVALID")

        original_rows: list[dict[str, str]] = []
        bridge_rows: list[dict[str, str]] = []
        audit_rows: list[dict[str, str]] = []
        if "original" in tables:
            headers, original_rows = tables["original"]
            if not required_original.issubset(headers):
                local_issues.append("ORIGINAL_VIEW_REQUIRED_IDENTITY_COLUMNS_MISSING")
            if _manifest_count(bridge_manifest, "original_row_count") != len(original_rows):
                local_issues.append("ORIGINAL_VIEW_ROW_COUNT_MISMATCH")
            for row in original_rows:
                if row.get("member_contract_version") != "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V6":
                    local_issues.append("ORIGINAL_VIEW_MEMBER_CONTRACT_NOT_V6")
                    break
                if row.get("view_contract") != "SOURCE_PRESENTATION_EXACT_V1":
                    local_issues.append("ORIGINAL_VIEW_CONTRACT_MISMATCH")
                    break
                if any(_is_blank_csv_value(row.get(field)) for field in (
                    "presentation_member_id", "presentation_regime", "source_row_ids",
                )):
                    local_issues.append("ORIGINAL_VIEW_SOURCE_IDENTITY_INCOMPLETE")
                    break

        if "bridge_long" in tables:
            headers, bridge_rows = tables["bridge_long"]
            if not required_bridge.issubset(headers):
                local_issues.append("BRIDGE_VIEW_REQUIRED_COLUMNS_MISSING")
            if _manifest_count(bridge_manifest, "bridge_row_count") != len(bridge_rows):
                local_issues.append("BRIDGE_VIEW_ROW_COUNT_MISMATCH")
            by_key: dict[str, list[dict[str, str]]] = {}
            for row in bridge_rows:
                if row.get("view_contract") != "FINANCIAL_INVESTMENT_STANDARDS_BRIDGE_V1":
                    local_issues.append("BRIDGE_VIEW_CONTRACT_MISMATCH")
                    break
                status = str(row.get("bridge_projection_status") or "")
                if status != "BRIDGE_READY_PARTIAL_COMPARABILITY" and not _is_blank_csv_value(row.get("final_value")):
                    local_issues.append("BLOCKED_BRIDGE_ROW_HAS_PROJECTED_VALUE")
                    break
                by_key.setdefault(str(row.get("bridge_semantic_key") or ""), []).append(row)
            for key, rows in by_key.items():
                if not key:
                    local_issues.append("BRIDGE_SEMANTIC_KEY_MISSING")
                    break
                if len(rows) > 1 and any(
                    row.get("bridge_projection_status") != "BRIDGE_AMBIGUOUS_SOURCE_SET"
                    or not _is_blank_csv_value(row.get("final_value"))
                    for row in rows
                ):
                    local_issues.append("SAME_PERIOD_MULTIPLE_SOURCE_NOT_FAILED_CLOSED")
                    break

        if "audit" in tables:
            _, audit_rows = tables["audit"]
            if _manifest_count(bridge_manifest, "audit_row_count") != len(audit_rows):
                local_issues.append("BRIDGE_AUDIT_ROW_COUNT_MISMATCH")
            blocking_statuses = {
                str(row.get("bridge_projection_status") or "")
                for row in bridge_rows
                if str(row.get("bridge_projection_status") or "")
                not in {"", "BRIDGE_READY_PARTIAL_COMPARABILITY"}
            }
            audit_statuses = {str(row.get("audit_status") or "") for row in audit_rows}
            if not blocking_statuses.issubset(audit_statuses):
                local_issues.append("BRIDGE_BLOCKER_NOT_RECORDED_IN_AUDIT")

        if "bridge_wide" in tables:
            wide_headers, _ = tables["bridge_wide"]
            if "analysis_bridge_group" not in wide_headers:
                local_issues.append("BRIDGE_WIDE_IDENTITY_MISSING")

        merge_audits.append({
            "merge_id": merge_id, "run_path": str(run_path),
            "original_row_count": len(original_rows),
            "bridge_row_count": len(bridge_rows),
            "audit_row_count": len(audit_rows),
            "issues": sorted(set(local_issues)),
        })
        issues.extend({"merge_id": merge_id, "issue": issue} for issue in sorted(set(local_issues)))
    return {
        "status": "PASS" if merge_audits and not issues else "FAIL",
        "merge_count": len(merge_audits),
        "issues": issues,
        "merge_audits": merge_audits,
    }


def financial_v6_shadow_stage_result(payload: Mapping[str, Any]) -> StageResult:
    """Normalize one real-PDF Evidence V2 shadow cell into a fail-closed gate."""
    required_truths = (
        "v2_pass", "golden_identity_match", "required_current_member_status_valid",
        "physical_row_identity_unique", "note_value_binding_verified",
    )
    issues: list[str] = []
    if payload.get("member_contract_version") != "FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V6":
        issues.append("FINANCIAL_MEMBER_CONTRACT_NOT_V6")
    for field in required_truths:
        if payload.get(field) is not True:
            issues.append(f"{field.upper()}_NOT_TRUE")
    if str(payload.get("shadow_status") or "") == "SHADOW_WORSE":
        issues.append("SHADOW_WORSE")
    if int(payload.get("cross_row_binding_conflicts") or 0) != 0:
        issues.append("CROSS_ROW_NOTE_VALUE_BINDING_CONFLICT")
    if int(payload.get("duplicate_active_member_occurrences") or 0) != 0:
        issues.append("DUPLICATE_ACTIVE_PRESENTATION_MEMBER")
    if not str(payload.get("presentation_regime") or "").strip():
        issues.append("PRESENTATION_REGIME_MISSING")
    if not str(payload.get("physical_source_row_ids") or "").strip():
        issues.append("PHYSICAL_SOURCE_ROW_IDS_MISSING")
    return StageResult(
        AcceptanceStage.DISCOVERY,
        AcceptanceStatus.PASS if not issues else AcceptanceStatus.FAIL,
        (
            "FINANCIAL_V6_PHYSICAL_IDENTITY_AND_BINDING_PASS"
            if not issues else "FINANCIAL_V6_PHYSICAL_IDENTITY_AND_BINDING_FAIL"
        ),
        {**dict(payload), "issues": issues},
    )


class ReadOnlyRegistrySnapshot:
    """Read persistent acceptance evidence without mutating DATA_HOME."""

    def __init__(self, metadata_db: Path):
        self.metadata_db = Path(metadata_db)

    def _connect(self) -> sqlite3.Connection:
        uri = f"file:{self.metadata_db.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _family_value(profile: RegistryProfile) -> str:
        return profile.family

    def pdf_asset(self, sha256_value: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM pdf_assets WHERE lower(sha256)=lower(?) AND lifecycle_status='ACTIVE'",
                (sha256_value,),
            ).fetchone()
            if row:
                return dict(row)
            # Some legacy v6.13 rows predate SHA projection into pdf_assets.
            # The canonical upload itself remains authoritative: shortlist by
            # the immutable filename prefix, then hash the real file before
            # accepting it.  A prefix alone is never sufficient.
            prefix = str(sha256_value or "").lower()[:12]
            candidates = conn.execute(
                """SELECT * FROM pdf_assets
                   WHERE lifecycle_status='ACTIVE' AND lower(filename) LIKE ?""",
                (prefix + "_%",),
            ).fetchall()
            for candidate in candidates:
                payload = dict(candidate)
                source_path = Path(str(payload.get("path") or ""))
                if not source_path.is_file():
                    continue
                digest = sha256()
                with source_path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest().lower() == str(sha256_value or "").lower():
                    payload["sha256_verified_from_file"] = digest.hexdigest()
                    return payload
            return None

    def occurrences(self, profile: RegistryProfile, company_name: str, year: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM statement_occurrences
                   WHERE table_family=? AND normalized_company=? AND report_year=?
                   ORDER BY created_at""",
                (self._family_value(profile), company_name, str(year)),
            ).fetchall()
            return [dict(row) for row in rows]

    def certified_links(self, profile: RegistryProfile, occurrence_ids: Iterable[str], year: int) -> list[dict[str, Any]]:
        occurrence_ids = tuple(occurrence_ids)
        if not occurrence_ids:
            return []
        placeholders = ",".join("?" for _ in occurrence_ids)
        query = f"""SELECT * FROM certified_child_table_links
                    WHERE table_family_id=? AND report_year=?
                      AND certification_status='CERTIFIED'
                      AND anchor_id IN ({placeholders})"""
        with self._connect() as conn:
            rows = conn.execute(query, (profile.family, str(year), *occurrence_ids)).fetchall()
            return [dict(row) for row in rows]

    def capture_snapshot(
        self,
        profile: RegistryProfile,
        sha256_value: str,
        *,
        research_batch_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        scoped_batches = tuple(
            str(value) for value in (research_batch_ids or ()) if str(value)
        )
        batch_clause = ""
        batch_params: tuple[str, ...] = ()
        if scoped_batches:
            batch_clause = " AND research_batch_id IN (" + ",".join(
                "?" for _ in scoped_batches
            ) + ")"
            batch_params = scoped_batches
        with self._connect() as conn:
            requests = conn.execute(
                f"""SELECT request_id,research_batch_id,status,member_table_id
                   FROM capture_requests
                   WHERE table_family_id=? AND (
                       lower(source_pdf_sha256)=lower(?) OR
                       lower(source_pdf_id) LIKE ?
                   ){batch_clause}""",
                (
                    profile.family, sha256_value,
                    "%" + str(sha256_value).lower()[:12] + "_%",
                    *batch_params,
                ),
            ).fetchall()
            request_ids = [row["request_id"] for row in requests]
            if not request_ids:
                return {"request_count": 0, "capture_count": 0, "merge_ready_count": 0, "captures": []}
            placeholders = ",".join("?" for _ in request_ids)
            captures = conn.execute(
                f"""SELECT c.*,
                            group_concat(DISTINCT r.member_table_id) AS acceptance_member_table_ids,
                            group_concat(DISTINCT COALESCE(
                                json_extract(bc.payload_json, '$.role'),
                                CASE WHEN bc.child_order=0 THEN 'PRIMARY_TABLE'
                                     ELSE 'UNCLASSIFIED' END
                            )) AS acceptance_block_roles,
                            min(bc.child_order) AS acceptance_child_order
                    FROM capture_bundles b
                    JOIN capture_requests r ON r.request_id=b.request_id
                    JOIN capture_bundle_children bc ON bc.bundle_id=b.bundle_id
                    JOIN captures c ON c.capture_id=bc.capture_id
                    WHERE b.request_id IN ({placeholders}) AND bc.status='CAPTURED'
                      AND c.is_trashed=0
                    GROUP BY c.capture_id""",
                request_ids,
            ).fetchall()
            capture_rows = [dict(row) for row in captures]
            role_counts: dict[str, int] = {}
            captured_member_tables: set[str] = set()
            for row in capture_rows:
                metadata_path = Path(str(row.get("run_path") or "")) / "capture_metadata.json"
                if profile.family == "investment_portfolio" and metadata_path.is_file():
                    try:
                        artifact_metadata = json.loads(
                            metadata_path.read_text(encoding="utf-8")
                        )
                    except (OSError, json.JSONDecodeError):
                        artifact_metadata = {}
                    artifact_member = str(
                        artifact_metadata.get("member_table_id")
                        or artifact_metadata.get("member_table")
                        or ""
                    ).strip()
                    if artifact_member:
                        row["acceptance_member_table_ids"] = artifact_member
                captured_member_tables.update(
                    value.strip() for value in str(
                        row.get("acceptance_member_table_ids") or ""
                    ).split(",") if value.strip()
                )
                for role in {
                    value.strip() for value in str(
                        row.get("acceptance_block_roles") or ""
                    ).split(",") if value.strip()
                }:
                    role_counts[role] = role_counts.get(role, 0) + 1
            return {
                "request_count": len(requests),
                "capture_count": len(capture_rows),
                "merge_ready_count": sum(int(row.get("merge_ready") or 0) for row in capture_rows),
                "captured_member_tables": sorted(captured_member_tables),
                "physical_block_role_counts": role_counts,
                "captures": capture_rows,
            }

    def merge_snapshot(
        self, capture_ids: Iterable[str], *, merge_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        capture_ids = tuple(capture_ids)
        if not capture_ids:
            return {"merge_count": 0, "merge_ids": []}
        placeholders = ",".join("?" for _ in capture_ids)
        scoped_merges = tuple(str(value) for value in (merge_ids or ()) if str(value))
        merge_clause = ""
        merge_params: tuple[str, ...] = ()
        if scoped_merges:
            merge_clause = " AND p.merge_id IN (" + ",".join("?" for _ in scoped_merges) + ")"
            merge_params = scoped_merges
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT p.merge_id,p.run_path,p.table_id,p.dependency_status
                    FROM merge_sources s
                    JOIN merge_projects p ON p.merge_id=s.merge_id
                    WHERE s.capture_id IN ({placeholders})
                      AND p.lifecycle_status='ACTIVE' AND p.is_trashed=0
                      {merge_clause}""",
                (*capture_ids, *merge_params),
            ).fetchall()
            merges = [dict(row) for row in rows]
            merge_ids = [str(row.get("merge_id") or "") for row in merges]
            return {
                "merge_count": len(merge_ids), "merge_ids": merge_ids,
                "merges": merges,
            }


class RegistryAcceptanceHarness:
    def __init__(
        self,
        *,
        corpus_root: Path,
        metadata_db: Path,
        research_batch_ids: Iterable[str] | None = None,
        formal_merge_ids: Iterable[str] | None = None,
        ui_parity_results: Mapping[tuple[str, str, int], StageResult] | None = None,
        financial_v6_evidence_results: Mapping[tuple[str, int], StageResult] | None = None,
    ):
        self.corpus_root = Path(corpus_root)
        self.snapshot = ReadOnlyRegistrySnapshot(metadata_db)
        self.research_batch_ids = tuple(
            str(value) for value in (research_batch_ids or ()) if str(value)
        )
        self.formal_merge_ids = tuple(
            str(value) for value in (formal_merge_ids or ()) if str(value)
        )
        self.ui_parity_results = dict(ui_parity_results or {})
        self.financial_v6_evidence_results = dict(financial_v6_evidence_results or {})

    def _financial_v6_evidence_result(
        self, company_id: str, year: int,
    ) -> StageResult:
        """Consume the read-only Evidence V2 shadow for the same filing.

        Certified occurrence rows may legitimately predate the V6 contract. The
        acceptance lane therefore supplies an immutable V6 shadow result instead
        of rewriting production certification assets merely to prove a code
        contract. Missing V6 evidence fails closed.
        """
        result = self.financial_v6_evidence_results.get((str(company_id), int(year)))
        if result is None:
            return StageResult(
                AcceptanceStage.DISCOVERY, AcceptanceStatus.NOT_RUN,
                "NOT_RUN_FINANCIAL_V6_EVIDENCE_REQUIRED", {},
            )
        if result.stage != AcceptanceStage.DISCOVERY:
            raise ValueError("FINANCIAL_V6_EVIDENCE_DISCOVERY_STAGE_REQUIRED")
        return result

    def _ui_parity_result(
        self, profile: RegistryProfile, company_id: str, year: int,
    ) -> StageResult:
        """Consume externally replayed UI evidence without running UI side effects."""
        result = self.ui_parity_results.get(
            (profile.definition_id, str(company_id), int(year))
        )
        if result is not None:
            if result.stage != AcceptanceStage.UI_PARITY:
                raise ValueError("UI_PARITY_STAGE_REQUIRED")
            return result
        return StageResult(
            AcceptanceStage.UI_PARITY, AcceptanceStatus.NOT_RUN,
            "NOT_RUN_REQUIRES_ISOLATED_FAKE_STREAMLIT_REPLAY", {},
        )

    def _load_cell(
        self, profile: RegistryProfile, company_id: str, year: int,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
        directory = profile.filing_dir(self.corpus_root, company_id, year)
        golden_path = directory / profile.golden_filename
        if not golden_path.is_file():
            return {}, {}, {}, directory
        golden = load_yaml(golden_path)
        sidecar_path = directory / sidecar_filename(profile.family)
        sidecar = load_yaml(sidecar_path) if sidecar_path.is_file() else {}
        filing_path = directory / "filing.yaml"
        filing = load_yaml(filing_path) if filing_path.is_file() else {}
        return golden, sidecar, filing, directory

    def _portfolio_capture_parity(
        self, *, company_name: str, year: int, captures: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        from golden_acceptance import compare_portfolio_capture_rows

        results_by_member: dict[str, dict[str, Any]] = {}
        for capture in captures:
            query = str(capture.get("table_query") or "")
            certified_members = {
                value.strip() for value in str(
                    capture.get("acceptance_member_table_ids") or ""
                ).split(",") if value.strip()
            }
            member_id = (
                next(iter(certified_members)) if len(certified_members) == 1
                else "portfolio_by_measurement" if "会计计量" in query
                else "portfolio_by_category" if "投资对象" in query or "投资品种" in query
                else "portfolio_summary" if "总览" in query
                else "portfolio_by_category" if "投资组合" in query
                else next(iter(certified_members), "") if len(certified_members) == 1
                else ""
            )
            result_path = Path(str(capture.get("run_path") or "")) / "table_capture_result.json"
            if member_id and result_path.is_file():
                candidate = json.loads(result_path.read_text(encoding="utf-8"))
                current = results_by_member.get(member_id) or {}
                if len(candidate.get("rows") or []) > len(current.get("rows") or []):
                    results_by_member[member_id] = candidate
        comparison = compare_portfolio_capture_rows(
            company_name, year, results_by_member, root=self.corpus_root,
        )
        mismatches = [
            row for row in comparison.get("rows") or []
            if row.get("result") != "MATCH"
        ]
        return {
            "status": comparison.get("status"),
            "row_count": comparison.get("row_count"),
            "mismatch_count": len(mismatches),
            "mismatch_samples": mismatches[:20],
            "members_checked": comparison.get("members_checked") or [],
            "golden_path": comparison.get("golden_path"),
        }

    def _financial_capture_parity(
        self, *, company_name: str, year: int, captures: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply the existing certified child-table comparator to every member.

        Runtime request metadata supplies the member identity.  The comparator
        reads only formal ``table_raw_long.csv`` evidence and never writes or
        backfills Golden values.
        """
        from golden_acceptance import compare_child_capture_csv

        captures_by_member: dict[str, list[dict[str, Any]]] = {}
        for capture in captures:
            members = [
                value.strip() for value in str(
                    capture.get("acceptance_member_table_ids") or ""
                ).split(",") if value.strip()
            ]
            if len(members) != 1:
                captures_by_member.setdefault("", []).append({
                    "capture_id": capture.get("capture_id"),
                    "reason": "CERTIFIED_MEMBER_IDENTITY_AMBIGUOUS",
                    "member_table_ids": members,
                })
                continue
            captures_by_member.setdefault(members[0], []).append(capture)

        audits: list[dict[str, Any]] = []
        for member_id, member_captures in sorted(captures_by_member.items()):
            if not member_id:
                audits.extend({
                    **capture,
                    "status": "MISMATCH",
                } for capture in member_captures)
                continue
            raw_long_paths = [
                Path(str(capture.get("run_path") or "")) / "table_raw_long.csv"
                for capture in member_captures
            ]
            comparison = compare_child_capture_csv(
                company_name, year, member_label=member_id,
                raw_long_path=raw_long_paths, root=self.corpus_root,
            )
            audits.append({
                "capture_ids": [capture.get("capture_id") for capture in member_captures],
                "member_table_id": member_id,
                "status": comparison.get("status"),
                "row_count": len(comparison.get("rows") or []),
                "mismatch_samples": [
                    row for row in comparison.get("rows") or []
                    if row.get("status") != "MATCH"
                ][:20],
                "golden_path": comparison.get("golden_path"),
                "error": comparison.get("error"),
            })
        return {
            "status": (
                "MATCH" if audits
                and all(item.get("status") == "MATCH" for item in audits)
                else "MISMATCH"
            ),
            "capture_count": len(audits),
            "member_audits": audits,
        }

    def evaluate(self, profile: RegistryProfile, company_id: str, year: int) -> FilingAcceptanceResult:
        golden, sidecar, filing_source, directory = self._load_cell(profile, company_id, year)
        company_name = COMPANY_NAMES[company_id]
        stages: list[StageResult] = []
        if not golden:
            stages.append(StageResult(
                AcceptanceStage.CORPUS_PREFLIGHT, AcceptanceStatus.BLOCKED,
                "BLOCKED_MISSING_CERTIFIED_GOLDEN", {"directory": str(directory)},
            ))
            return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, "", tuple(stages))
        if not sidecar:
            stages.append(StageResult(
                AcceptanceStage.CORPUS_PREFLIGHT, AcceptanceStatus.BLOCKED,
                "BLOCKED_GOLDEN_IDENTITY_V1_2_MISSING",
                {"expected": str(directory / sidecar_filename(profile.family))},
            ))
            return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, "", tuple(stages))
        identity = validate_identity_source_consistency(
            sidecar, golden, filing=filing_source, strict=True,
            expected_family=profile.family,
            expected_definition_id=profile.definition_id,
        )
        filing = dict(sidecar.get("filing_identity") or {})
        sha_value = str(filing.get("pdf_sha256") or "").lower()
        if identity.status != "PASS":
            stages.append(StageResult(
                AcceptanceStage.CORPUS_PREFLIGHT, AcceptanceStatus.FAIL,
                "GOLDEN_IDENTITY_V1_2_INVALID",
                {"issues": list(identity.issues), "row_count": identity.row_count, "table_count": identity.table_count},
            ))
            return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, sha_value, tuple(stages))
        pdf_asset = self.snapshot.pdf_asset(sha_value)
        if not pdf_asset:
            stages.append(StageResult(
                AcceptanceStage.CORPUS_PREFLIGHT, AcceptanceStatus.BLOCKED,
                "BLOCKED_CANONICAL_PDF_IDENTITY_NOT_ACTIVE",
                {"pdf_sha256": sha_value, "golden_directory": str(directory)},
            ))
            return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, sha_value, tuple(stages))
        stages.append(StageResult(
            AcceptanceStage.CORPUS_PREFLIGHT, AcceptanceStatus.PASS,
            "GOLDEN_AND_PDF_IDENTITY_MATCH",
            {"row_count": identity.row_count, "table_count": identity.table_count, "pdf_id": pdf_asset.get("pdf_id")},
        ))
        occurrences = self.snapshot.occurrences(profile, company_name, year)
        certified_occurrences = [row for row in occurrences if row.get("status") == "ANCHOR_CERTIFIED"]
        if not certified_occurrences:
            stages.append(StageResult(
                AcceptanceStage.DISCOVERY, AcceptanceStatus.BLOCKED,
                "BLOCKED_DISCOVERY_OR_ANCHOR_CERTIFICATION_REQUIRED",
                {"occurrence_count": len(occurrences)},
            ))
            return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, sha_value, tuple(stages))
        if profile.family == "financial_investment":
            v6_evidence = self._financial_v6_evidence_result(company_id, year)
            if v6_evidence.status != AcceptanceStatus.PASS:
                stages.append(v6_evidence)
                return FilingAcceptanceResult(
                    profile.definition_id, profile.family, company_id,
                    company_name, year, sha_value, tuple(stages),
                )
            stages.append(StageResult(
                AcceptanceStage.DISCOVERY, AcceptanceStatus.PASS,
                "CERTIFIED_OCCURRENCE_AND_FINANCIAL_V6_EVIDENCE_PRESENT",
                {
                    "occurrence_ids": [row["occurrence_id"] for row in certified_occurrences],
                    "financial_v6_evidence": v6_evidence.evidence,
                },
            ))
        else:
            stages.append(StageResult(
                AcceptanceStage.DISCOVERY, AcceptanceStatus.PASS,
                "CERTIFIED_OCCURRENCE_PRESENT",
                {"occurrence_ids": [row["occurrence_id"] for row in certified_occurrences]},
            ))
        links = self.snapshot.certified_links(
            profile, [row["occurrence_id"] for row in certified_occurrences], year,
        )
        linked_members = {str(row.get("member_table_id") or "") for row in links}
        if profile.family == "investment_portfolio":
            evidence_members: set[str] = set()
            for row in links:
                for field in ("score_snapshot_json", "evidence_snapshot_json"):
                    try:
                        payload = json.loads(row.get(field) or "{}")
                    except json.JSONDecodeError:
                        payload = {}
                    evidence_members.update(str(value) for value in payload.get("member_table_ids") or [])
            linked_members.update(evidence_members)
        expected_members = {
            str(row.get("member_table_id") or "")
            for row in sidecar.get("rows") or []
            if row.get("member_table_id")
            and (
                profile.family == "investment_portfolio"
                or row.get("row_kind") == "MEMBER"
            )
        }
        if not expected_members:
            expected_members = set(profile.required_member_tables)
        missing_members = sorted(expected_members - linked_members)
        if missing_members:
            stages.append(StageResult(
                AcceptanceStage.CERTIFICATION_SNAPSHOT, AcceptanceStatus.BLOCKED,
                "BLOCKED_CERTIFICATION_REQUIRED",
                {"certified_link_count": len(links), "missing_member_tables": missing_members},
            ))
            return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, sha_value, tuple(stages))
        stages.append(StageResult(
            AcceptanceStage.CERTIFICATION_SNAPSHOT, AcceptanceStatus.PASS,
            "CERTIFIED_REQUIRED_TARGETS_PRESENT",
            {"certified_link_count": len(links), "member_tables": sorted(linked_members)},
        ))
        capture = self.snapshot.capture_snapshot(
            profile, sha_value,
            research_batch_ids=self.research_batch_ids,
        )
        if not capture["capture_count"] or capture["merge_ready_count"] != capture["capture_count"]:
            stages.append(StageResult(
                AcceptanceStage.CAPTURE, AcceptanceStatus.BLOCKED,
                "BLOCKED_CAPTURE_NOT_COMPLETE_OR_NOT_MERGE_READY", capture,
            ))
            return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, sha_value, tuple(stages))
        missing_capture_members = sorted(
            expected_members - set(capture.get("captured_member_tables") or [])
        )
        if missing_capture_members:
            stages.append(StageResult(
                AcceptanceStage.CAPTURE, AcceptanceStatus.BLOCKED,
                "BLOCKED_CAPTURE_REQUIRED_MEMBER_MISSING",
                {
                    **{key: value for key, value in capture.items() if key != "captures"},
                    "missing_member_tables": missing_capture_members,
                },
            ))
            return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, sha_value, tuple(stages))
        golden_parity: dict[str, Any] = {"status": "NOT_APPLICABLE"}
        if profile.family == "investment_portfolio":
            golden_parity = self._portfolio_capture_parity(
                company_name=company_name, year=year, captures=capture["captures"],
            )
        elif profile.family == "financial_investment":
            golden_parity = self._financial_capture_parity(
                company_name=company_name, year=year, captures=capture["captures"],
            )
        if profile.family in {"investment_portfolio", "financial_investment"}:
            if golden_parity.get("status") != "MATCH":
                stages.append(StageResult(
                    AcceptanceStage.CAPTURE, AcceptanceStatus.FAIL,
                    "CAPTURE_GOLDEN_IDENTITY_OR_DATA_MISMATCH",
                    {**{key: value for key, value in capture.items() if key != "captures"},
                     "golden_parity": golden_parity},
                ))
                return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, sha_value, tuple(stages))
        stages.append(StageResult(
            AcceptanceStage.CAPTURE, AcceptanceStatus.PASS,
            "CAPTURE_ASSETS_MERGE_READY_AND_GOLDEN_MATCH",
            {**{key: value for key, value in capture.items() if key != "captures"},
             "golden_parity": golden_parity},
        ))
        # Canonical is materialized by the formal Merge service.  The harness
        # verifies persistent Merge membership rather than manufacturing a
        # second Canonical artifact.
        merge = self.snapshot.merge_snapshot(
            (row["capture_id"] for row in capture["captures"]),
            merge_ids=self.formal_merge_ids,
        )
        if not merge["merge_count"]:
            stages.extend((
                StageResult(AcceptanceStage.CANONICAL, AcceptanceStatus.NOT_RUN, "NOT_RUN_NO_FORMAL_MERGE_MEMBERSHIP", {}),
                StageResult(AcceptanceStage.MERGE, AcceptanceStatus.NOT_RUN, "NOT_RUN_NO_FORMAL_MERGE_PROJECT", merge),
            ))
        else:
            stages.append(StageResult(
                AcceptanceStage.CANONICAL, AcceptanceStatus.PASS,
                "FORMAL_MERGE_CONSUMED_CAPTURE", merge,
            ))
            if profile.family == "financial_investment":
                bridge = validate_financial_merge_artifacts(merge.get("merges") or [])
                stages.append(StageResult(
                    AcceptanceStage.MERGE,
                    AcceptanceStatus.PASS if bridge["status"] == "PASS" else AcceptanceStatus.FAIL,
                    (
                        "FINANCIAL_V6_DUAL_VIEW_MERGE_CONTRACT_PASS"
                        if bridge["status"] == "PASS"
                        else "FINANCIAL_V6_DUAL_VIEW_MERGE_CONTRACT_FAIL"
                    ),
                    {**merge, "financial_v6_bridge": bridge},
                ))
            else:
                stages.append(StageResult(
                    AcceptanceStage.MERGE, AcceptanceStatus.PASS,
                    "FORMAL_MERGE_MEMBERSHIP_PRESENT", merge,
                ))
        ui_result = self._ui_parity_result(profile, company_id, year)
        if (
            profile.family == "financial_investment"
            and ui_result.status == AcceptanceStatus.PASS
            and ui_result.evidence.get("financial_v6_identity_fields_compared") is not True
        ):
            ui_result = StageResult(
                AcceptanceStage.UI_PARITY, AcceptanceStatus.FAIL,
                "UI_OFFLINE_FINANCIAL_V6_IDENTITY_NOT_COMPARED",
                dict(ui_result.evidence),
            )
        stages.append(ui_result)
        return FilingAcceptanceResult(profile.definition_id, profile.family, company_id, company_name, year, sha_value, tuple(stages))

    def evaluate_profile(self, profile: RegistryProfile) -> list[FilingAcceptanceResult]:
        return [
            self.evaluate(profile, company_id, year)
            for company_id in profile.company_dirs
            for year in (2023, 2024, 2025)
        ]


def semantic_lane_fingerprint(rows: Iterable[dict[str, Any]]) -> tuple[tuple[Any, ...], ...]:
    """Compare offline/UI semantics while ignoring volatile IDs and timestamps."""
    keys = (
        "company_id", "report_year", "family", "physical_table_id",
        "member_table_id", "presentation_member_id", "presentation_regime",
        "member_contract_version", "analysis_bridge_group",
        "bridge_rule_id", "bridge_projection_status", "classification_axis", "semantic_row_key",
        "parent_semantic_row_key", "period_identity", "measure", "unit", "value",
        "quality_status", "review_status", "merge_ready",
    )
    return tuple(sorted(tuple(row.get(key) for key in keys) for row in rows))


def compare_ui_offline_lanes(
    offline_rows: Iterable[dict[str, Any]], ui_rows: Iterable[dict[str, Any]],
) -> StageResult:
    offline = semantic_lane_fingerprint(offline_rows)
    ui = semantic_lane_fingerprint(ui_rows)
    return StageResult(
        AcceptanceStage.UI_PARITY,
        AcceptanceStatus.PASS if offline == ui else AcceptanceStatus.FAIL,
        "UI_OFFLINE_SEMANTIC_PARITY" if offline == ui else "UI_OFFLINE_SEMANTIC_DRIFT",
        {"offline_count": len(offline), "ui_count": len(ui)},
    )
