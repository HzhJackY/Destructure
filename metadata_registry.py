#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite metadata control plane for Financial Metric Resolver v6.1.

Large financial data stays in PDF/CSV/Parquet/JSON. SQLite stores only metadata,
lineage, lifecycle, dependency, and job state so UI/API layers do not need to
rescan thousands of directories on every interaction.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from version import REGISTRY_SCHEMA_VERSION


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


import threading

_schema_initialized_paths: set[Path] = set()
_schema_init_lock = threading.Lock()


class MetadataRegistry:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with _schema_init_lock:
            if self.db_path not in _schema_initialized_paths:
                self.initialize_schema()
                _schema_initialized_paths.add(self.db_path)

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=60.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            if conn.in_transaction:
                conn.commit()
        except Exception:
            if conn.in_transaction:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pdf_assets (
                    pdf_id TEXT PRIMARY KEY,
                    filename TEXT,
                    display_name TEXT,
                    sha256 TEXT,
                    company TEXT,
                    document_year TEXT,
                    size_bytes INTEGER,
                    path TEXT UNIQUE,
                    modified_at TEXT,
                    created_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pdf_company_year
                    ON pdf_assets(company, document_year);

                CREATE TABLE IF NOT EXISTS capture_batches (
                    batch_id TEXT PRIMARY KEY,
                    batch_status TEXT NOT NULL DEFAULT 'ACTIVE',
                    table_query TEXT,
                    capture_count INTEGER NOT NULL DEFAULT 0,
                    active_count INTEGER NOT NULL DEFAULT 0,
                    invalidated_count INTEGER NOT NULL DEFAULT 0,
                    trashed_count INTEGER NOT NULL DEFAULT 0,
                    producer_versions TEXT,
                    first_created_at TEXT,
                    last_created_at TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS captures (
                    capture_id TEXT PRIMARY KEY,
                    run_path TEXT NOT NULL UNIQUE,
                    pdf_id TEXT,
                    pdf_name TEXT,
                    source_pdf_display TEXT,
                    company TEXT,
                    document_year TEXT,
                    table_query TEXT,
                    table_family_id TEXT,
                    schema_variant TEXT,
                    note_number TEXT,
                    batch_id TEXT,
                    producer_version TEXT,
                    header_parser TEXT,
                    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
                    boundary_status TEXT,
                    header_dimension_status TEXT,
                    merge_ready INTEGER NOT NULL DEFAULT 0,
                    row_count_official INTEGER,
                    invalidation_reason_code TEXT,
                    invalidation_note TEXT,
                    supersedes_capture_id TEXT,
                    superseded_by_capture_id TEXT,
                    is_trashed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(pdf_id) REFERENCES pdf_assets(pdf_id) ON DELETE SET NULL,
                    FOREIGN KEY(batch_id) REFERENCES capture_batches(batch_id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_capture_lifecycle
                    ON captures(lifecycle_status, is_trashed);
                CREATE INDEX IF NOT EXISTS idx_capture_company_year
                    ON captures(company, document_year);
                CREATE INDEX IF NOT EXISTS idx_capture_table
                    ON captures(table_query);
                CREATE INDEX IF NOT EXISTS idx_capture_batch
                    ON captures(batch_id);
                CREATE INDEX IF NOT EXISTS idx_capture_created
                    ON captures(created_at DESC);

                CREATE TABLE IF NOT EXISTS merge_projects (
                    merge_id TEXT PRIMARY KEY,
                    run_path TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    table_id TEXT,
                    source_count INTEGER NOT NULL DEFAULT 0,
                    lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
                    dependency_status TEXT NOT NULL DEFAULT 'CURRENT',
                    stale_capture_run_ids_json TEXT,
                    created_at TEXT,
                    updated_at TEXT NOT NULL,
                    is_trashed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_merge_dependency_status
                    ON merge_projects(dependency_status, is_trashed);

                CREATE TABLE IF NOT EXISTS merge_sources (
                    merge_id TEXT NOT NULL,
                    capture_id TEXT NOT NULL,
                    source_order INTEGER,
                    PRIMARY KEY(merge_id, capture_id),
                    FOREIGN KEY(merge_id) REFERENCES merge_projects(merge_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_merge_sources_capture
                    ON merge_sources(capture_id);

                CREATE TABLE IF NOT EXISTS asset_dependencies (
                    parent_type TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    child_type TEXT NOT NULL,
                    child_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(parent_type, parent_id, child_type, child_id, relation)
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    batch_id TEXT,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    source_asset_id TEXT,
                    target_asset_id TEXT,
                    error_type TEXT,
                    error_message TEXT,
                    payload_json TEXT,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_batch_status
                    ON jobs(batch_id, status);
                CREATE INDEX IF NOT EXISTS idx_jobs_created
                    ON jobs(created_at DESC);

                CREATE TABLE IF NOT EXISTS registry_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    asset_type TEXT,
                    asset_id TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );

                -- v6.3: semantic metadata is additive.  Immutable Capture
                -- artifacts remain the source of truth and can rebuild this index.
                CREATE TABLE IF NOT EXISTS capture_semantics (
                    capture_id TEXT PRIMARY KEY,
                    table_family TEXT,
                    member_table TEXT,
                    source_table_title TEXT,
                    note_reference TEXT,
                    statement_anchor_json TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS statement_note_edges (
                    edge_id TEXT PRIMARY KEY,
                    pdf_id TEXT,
                    company TEXT,
                    report_year TEXT,
                    statement_type TEXT,
                    statement_item TEXT NOT NULL,
                    note_reference TEXT,
                    member_table TEXT,
                    statement_page INTEGER,
                    note_page INTEGER,
                    locator_method TEXT,
                    confidence REAL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_statement_note_edge_ref
                    ON statement_note_edges(pdf_id, note_reference);
                CREATE TABLE IF NOT EXISTS table_notes (
                    note_id TEXT PRIMARY KEY,
                    capture_id TEXT,
                    table_family TEXT,
                    member_table TEXT,
                    note_scope TEXT NOT NULL,
                    target_row_path TEXT,
                    target_column_dimension_json TEXT,
                    note_marker TEXT,
                    raw_text TEXT NOT NULL,
                    normalized_text TEXT,
                    page INTEGER,
                    bbox_json TEXT,
                    classification TEXT,
                    confidence REAL,
                    source_lineage_json TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(capture_id) REFERENCES captures(capture_id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_table_notes_capture ON table_notes(capture_id);

                -- v6.4: discovery evidence is append-only; certification is a
                -- separate materialized knowledge layer, never a rewrite of PDF evidence.
                CREATE TABLE IF NOT EXISTS machine_discoveries (
                    discovery_id TEXT PRIMARY KEY, pdf_id TEXT, company TEXT, normalized_company TEXT,
                    report_year TEXT, filing_type TEXT, statement_type TEXT, display_name TEXT,
                    table_family TEXT, statement_item TEXT, note_reference TEXT, statement_value REAL,
                    member_table TEXT, source_table_title TEXT, section_context TEXT, statement_page INTEGER,
                    note_page INTEGER, locator_method TEXT, confidence REAL, reconciliation_status TEXT,
                    status TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_machine_discovery_lookup
                    ON machine_discoveries(normalized_company,filing_type,statement_type,display_name,status);
                CREATE TABLE IF NOT EXISTS discovery_adjudications (
                    action_id TEXT PRIMARY KEY, discovery_id TEXT NOT NULL, label TEXT NOT NULL, actor TEXT,
                    reason TEXT, scope TEXT, old_json TEXT NOT NULL, new_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(discovery_id) REFERENCES machine_discoveries(discovery_id)
                );
                CREATE INDEX IF NOT EXISTS idx_discovery_adjudication_discovery ON discovery_adjudications(discovery_id,created_at);
                CREATE TABLE IF NOT EXISTS certified_discoveries (
                    certified_id TEXT PRIMARY KEY, discovery_id TEXT NOT NULL, company TEXT, normalized_company TEXT,
                    report_year TEXT, filing_type TEXT, statement_type TEXT, display_name TEXT, table_family TEXT,
                    member_table TEXT, source_table_title TEXT, note_reference_pattern TEXT, section_context TEXT,
                    applicability_scope TEXT, status TEXT NOT NULL, confidence REAL, success_count INTEGER NOT NULL DEFAULT 0,
                    rejection_count INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(discovery_id) REFERENCES machine_discoveries(discovery_id)
                );
                CREATE INDEX IF NOT EXISTS idx_certified_discovery_fastpath
                    ON certified_discoveries(normalized_company,filing_type,statement_type,display_name,member_table,archived);
                CREATE TABLE IF NOT EXISTS discovery_training_examples (
                    example_id TEXT PRIMARY KEY, discovery_id TEXT NOT NULL, context_json TEXT NOT NULL,
                    machine_confidence REAL, label TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS note_locator_training_examples (
                    example_id TEXT PRIMARY KEY, discovery_id TEXT NOT NULL, context_json TEXT NOT NULL,
                    machine_confidence REAL, label TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS structure_training_examples (
                    example_id TEXT PRIMARY KEY, discovery_id TEXT, context_json TEXT NOT NULL,
                    machine_confidence REAL, label TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS canonical_mapping_training_examples (
                    example_id TEXT PRIMARY KEY, discovery_id TEXT, context_json TEXT NOT NULL,
                    machine_confidence REAL, label TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                """
            )
            # v6.5 migrations are additive. Existing v6.4 evidence stays
            # readable; new statement-anchored metadata is never backfilled by
            # guessing values or pages.
            existing = {r[1] for r in conn.execute("PRAGMA table_info(machine_discoveries)").fetchall()}
            for name, ddl in {
                "scope": "TEXT", "note_reference_section": "TEXT", "note_reference_item": "TEXT",
                "note_reference_raw": "TEXT", "note_reference_normalized": "TEXT",
                "note_reference_status": "TEXT", "statement_pdf_page_index": "INTEGER",
                "statement_printed_page": "TEXT", "candidate_note_pdf_page_index": "INTEGER",
                "candidate_note_printed_page": "TEXT", "confirmed_note_pdf_page_index": "INTEGER",
                "confirmed_note_printed_page": "TEXT", "candidate_note_pages_json": "TEXT",
                "bbox_json": "TEXT", "candidate_cluster_id": "TEXT",
            }.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE machine_discoveries ADD COLUMN {name} {ddl}")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS statement_occurrences (
                    occurrence_id TEXT PRIMARY KEY, pdf_id TEXT, company TEXT, normalized_company TEXT,
                    report_year TEXT, filing_type TEXT, statement_type TEXT, scope TEXT,
                    display_name TEXT NOT NULL, table_family TEXT NOT NULL, source_table_title TEXT,
                    statement_pdf_page_index INTEGER, statement_printed_page TEXT,
                    parent_text TEXT NOT NULL, child_rows_json TEXT NOT NULL,
                    anchor_score REAL, status TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_statement_occurrences_lookup
                    ON statement_occurrences(normalized_company,filing_type,statement_type,scope,display_name,status);
                CREATE TABLE IF NOT EXISTS anchor_adjudications (
                    action_id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL, label TEXT NOT NULL,
                    actor TEXT, reason TEXT, chosen_scope TEXT, old_json TEXT NOT NULL,
                    new_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(occurrence_id) REFERENCES statement_occurrences(occurrence_id)
                );
                CREATE TABLE IF NOT EXISTS anchor_candidate_scores (
                    score_id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL,
                    total_score REAL NOT NULL, qualification_tier TEXT NOT NULL,
                    hard_gates_passed INTEGER NOT NULL, ranking_version TEXT NOT NULL,
                    score_components_json TEXT NOT NULL, positive_evidence_json TEXT NOT NULL,
                    negative_evidence_json TEXT NOT NULL, hard_gate_results_json TEXT NOT NULL,
                    recommendation_state TEXT, selection_state TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(occurrence_id,ranking_version)
                );
                CREATE TABLE IF NOT EXISTS anchor_certification_audit (
                    audit_id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL,
                    selection_method TEXT NOT NULL, recommended_candidate_id TEXT,
                    selected_candidate_id TEXT NOT NULL, candidate_score REAL,
                    score_evidence_snapshot_json TEXT NOT NULL,
                    alternative_candidates_json TEXT NOT NULL, override_reason TEXT,
                    actor TEXT, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS anchor_review_queue (
                    anchor_review_item_id TEXT PRIMARY KEY, source_pdf_id TEXT NOT NULL,
                    statement_scope TEXT NOT NULL, display_name TEXT NOT NULL,
                    candidate_ids_json TEXT NOT NULL, primary_review_reason TEXT NOT NULL,
                    severity TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(source_pdf_id,statement_scope,display_name)
                );
                CREATE TABLE IF NOT EXISTS discovery_candidate_clusters (
                    cluster_id TEXT PRIMARY KEY, normalized_company TEXT, report_year TEXT,
                    display_name TEXT, statement_type TEXT, scope TEXT, member_table TEXT,
                    candidate_note_pdf_page_index INTEGER, confidence REAL NOT NULL,
                    status TEXT NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capture_plans (
                    plan_id TEXT PRIMARY KEY, pdf_id TEXT, table_family TEXT NOT NULL,
                    status TEXT NOT NULL, anchor_occurrence_id TEXT, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS capture_plan_items (
                    item_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, member_table TEXT NOT NULL,
                    member_table_role TEXT NOT NULL, capture_mode TEXT NOT NULL, capture_order INTEGER,
                    note_reference TEXT, source_pdf_page_index INTEGER, candidate_note_pdf_page_index INTEGER,
                    confirmed_note_pdf_page_index INTEGER, status TEXT NOT NULL, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(plan_id) REFERENCES capture_plans(plan_id)
                );
                CREATE INDEX IF NOT EXISTS idx_capture_plan_items_plan ON capture_plan_items(plan_id,capture_order);
                CREATE TABLE IF NOT EXISTS certified_note_targets (
                    note_target_id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL, member_table TEXT NOT NULL,
                    note_reference TEXT NOT NULL, source_pdf_id TEXT, confirmed_note_pdf_page_index INTEGER,
                    target_heading TEXT, locator_method TEXT, confidence REAL, status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, actor TEXT, created_at TEXT NOT NULL,
                    FOREIGN KEY(occurrence_id) REFERENCES statement_occurrences(occurrence_id)
                );
                CREATE INDEX IF NOT EXISTS idx_certified_note_targets_lookup
                    ON certified_note_targets(occurrence_id,member_table,status);
                CREATE TABLE IF NOT EXISTS research_batches (
                    research_batch_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, table_family TEXT NOT NULL,
                    status TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS research_batch_members (
                    research_batch_id TEXT NOT NULL, plan_id TEXT, source_batch_id TEXT,
                    role TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(research_batch_id, plan_id, source_batch_id, role)
                );

                -- v6.7: registry-driven acquisition semantics.  These tables
                -- are additive; old captures/evidence remain immutable.
                CREATE TABLE IF NOT EXISTS discovery_strategies (
                    strategy_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, plugin_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS table_families (
                    family_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, definition_version TEXT NOT NULL,
                    discovery_strategy TEXT NOT NULL, payload_json TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS family_members (
                    member_id TEXT NOT NULL, family_id TEXT NOT NULL, display_name TEXT NOT NULL,
                    member_role TEXT NOT NULL, required INTEGER NOT NULL DEFAULT 0, canonical_order INTEGER,
                    payload_json TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(member_id, family_id),
                    FOREIGN KEY(family_id) REFERENCES table_families(family_id)
                );
                CREATE TABLE IF NOT EXISTS research_metrics (
                    metric_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, payload_json TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS metric_family_mappings (
                    mapping_id TEXT PRIMARY KEY, metric_id TEXT NOT NULL, family_id TEXT NOT NULL, member_id TEXT,
                    row_path_hint TEXT, priority INTEGER NOT NULL DEFAULT 100, payload_json TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_definitions (
                    definition_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, definition_version TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_definition_audit (
                    audit_id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT,
                    old_json TEXT NOT NULL, new_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(definition_id) REFERENCES research_definitions(definition_id)
                );
                -- v6.10: analysis domains group multiple table families under a
                -- research lens without collapsing their source identities.
                CREATE TABLE IF NOT EXISTS analysis_domains (
                    domain_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                    description TEXT, payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                -- v6.10: bridge contracts map concepts across families within a
                -- domain. 同一个经济概念在两个表族出现时必须拥有不同的 source
                -- identity, measurement basis 和 disclosure context.
                CREATE TABLE IF NOT EXISTS domain_bridge_contracts (
                    bridge_contract_id TEXT PRIMARY KEY, domain_id TEXT NOT NULL,
                    source_family_id TEXT NOT NULL, source_member_id TEXT,
                    target_family_id TEXT, target_member_id TEXT,
                    analysis_bucket TEXT, comparability_status TEXT NOT NULL,
                    measurement_basis TEXT, disclosure_context TEXT,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(domain_id) REFERENCES analysis_domains(domain_id)
                );
                CREATE INDEX IF NOT EXISTS idx_family_members_family ON family_members(family_id,canonical_order);
                CREATE INDEX IF NOT EXISTS idx_metric_family_mapping ON metric_family_mappings(metric_id,family_id);

                -- v6.9: a compound note is a container which can yield several
                -- independently auditable table blocks.  These records are
                -- additive and never replace raw capture evidence.
                CREATE TABLE IF NOT EXISTS note_containers (
                    container_id TEXT PRIMARY KEY, source_pdf_id TEXT, source_pdf_sha256 TEXT,
                    source_pdf_path TEXT, note_reference TEXT, note_title TEXT,
                    start_pdf_page INTEGER, end_pdf_page INTEGER, context_json TEXT NOT NULL,
                    layout_graph_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS table_blocks (
                    block_id TEXT PRIMARY KEY, container_id TEXT NOT NULL, block_order INTEGER NOT NULL,
                    block_title TEXT, block_role TEXT NOT NULL,
                    classification_axis TEXT NOT NULL DEFAULT 'UNRESOLVED',
                    block_terminal_type TEXT NOT NULL DEFAULT 'UNRESOLVED',
                    start_pdf_page INTEGER,
                    end_pdf_page INTEGER, bbox_json TEXT NOT NULL, header_topology_json TEXT NOT NULL,
                    semantic_graph_json TEXT NOT NULL, reconciliation_json TEXT NOT NULL,
                    quality_status TEXT NOT NULL, status TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(container_id) REFERENCES note_containers(container_id)
                );
                CREATE INDEX IF NOT EXISTS idx_table_blocks_container ON table_blocks(container_id,block_order);
                CREATE TABLE IF NOT EXISTS capture_bundles (
                    bundle_id TEXT PRIMARY KEY, request_id TEXT, container_id TEXT NOT NULL,
                    table_family_id TEXT, member_table_id TEXT, status TEXT NOT NULL,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(container_id) REFERENCES note_containers(container_id)
                );
                CREATE TABLE IF NOT EXISTS capture_bundle_children (
                    bundle_id TEXT NOT NULL, block_id TEXT NOT NULL, capture_id TEXT,
                    logical_asset_id TEXT, child_order INTEGER NOT NULL, status TEXT NOT NULL,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(bundle_id,block_id),
                    FOREIGN KEY(bundle_id) REFERENCES capture_bundles(bundle_id),
                    FOREIGN KEY(block_id) REFERENCES table_blocks(block_id)
                );
                CREATE TABLE IF NOT EXISTS layout_evidence_cache (
                    cache_key TEXT PRIMARY KEY, source_pdf_sha256 TEXT NOT NULL,
                    pdf_page_index INTEGER NOT NULL, extractor_version TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS block_adjudications (
                    action_id TEXT PRIMARY KEY, block_id TEXT NOT NULL, action TEXT NOT NULL,
                    actor TEXT, old_json TEXT NOT NULL, new_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, FOREIGN KEY(block_id) REFERENCES table_blocks(block_id)
                );
                CREATE TABLE IF NOT EXISTS reconciliation_relationships (
                    relationship_id TEXT PRIMARY KEY, container_id TEXT, block_id TEXT,
                    relation_type TEXT NOT NULL, status TEXT NOT NULL, confidence REAL,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ml_label_schemas (
                    schema_id TEXT PRIMARY KEY, label_name TEXT NOT NULL, version TEXT NOT NULL,
                    payload_json TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ml_labels (
                    label_id TEXT PRIMARY KEY, schema_id TEXT NOT NULL, entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL, label_value TEXT NOT NULL, actor TEXT,
                    evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(schema_id) REFERENCES ml_label_schemas(schema_id)
                );
                CREATE TABLE IF NOT EXISTS golden_certifications (
                    certification_id TEXT PRIMARY KEY, fixture_name TEXT NOT NULL,
                    source_pdf_sha256 TEXT, scope TEXT NOT NULL, status TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capture_review_records (
                    review_record_id TEXT PRIMARY KEY, logical_asset_id TEXT NOT NULL,
                    capture_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL,
                    reason TEXT, override_json TEXT NOT NULL, before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL, impact_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_capture_review_records_version
                    ON capture_review_records(capture_id,created_at);
                CREATE TABLE IF NOT EXISTS review_issues (
                    review_issue_id TEXT PRIMARY KEY, capture_version_id TEXT NOT NULL,
                    table_block_id TEXT, review_task_type TEXT NOT NULL,
                    reason_code TEXT NOT NULL, human_title TEXT NOT NULL,
                    human_description TEXT NOT NULL, severity TEXT NOT NULL,
                    blocking INTEGER NOT NULL, affected_object_type TEXT,
                    affected_object_id TEXT, evidence_json TEXT NOT NULL,
                    recommended_action TEXT NOT NULL, source_quality_gate TEXT,
                    status TEXT NOT NULL, derivation_key TEXT NOT NULL UNIQUE,
                    migration_version TEXT NOT NULL, created_at TEXT NOT NULL,
                    resolved_at TEXT, reviewer TEXT, decision TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_review_issues_capture
                    ON review_issues(capture_version_id,status,severity);
                CREATE TABLE IF NOT EXISTS review_tasks (
                    task_id TEXT PRIMARY KEY, capture_version_id TEXT NOT NULL,
                    task_type TEXT NOT NULL, required INTEGER NOT NULL,
                    status TEXT NOT NULL, reason_codes_json TEXT NOT NULL,
                    severity TEXT NOT NULL, blocking INTEGER NOT NULL,
                    affected_block TEXT, affected_rows_json TEXT NOT NULL,
                    affected_columns_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    recommended_action TEXT NOT NULL, reviewer TEXT, decision TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(capture_version_id,task_type)
                );
                CREATE INDEX IF NOT EXISTS idx_review_tasks_capture
                    ON review_tasks(capture_version_id,status,required);
                CREATE TABLE IF NOT EXISTS review_task_decisions (
                    decision_id TEXT PRIMARY KEY, capture_version_id TEXT NOT NULL,
                    task_id TEXT NOT NULL, task_type TEXT NOT NULL,
                    previous_status TEXT NOT NULL, new_status TEXT NOT NULL,
                    reviewer TEXT NOT NULL, reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_task_decisions_capture
                    ON review_task_decisions(capture_version_id,created_at);
                CREATE TABLE IF NOT EXISTS statement_scope_selections (
                    scope_selection_id TEXT PRIMARY KEY, research_project_id TEXT,
                    research_task_id TEXT, research_definition_id TEXT,
                    source_pdf_id TEXT NOT NULL, requested_scope TEXT NOT NULL,
                    default_scope TEXT NOT NULL, selection_source TEXT NOT NULL,
                    selected_by TEXT NOT NULL, selected_at TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, producer_version TEXT NOT NULL,
                    UNIQUE(research_task_id,source_pdf_id,requested_scope)
                );
                CREATE TABLE IF NOT EXISTS anchor_child_concepts (
                    anchor_child_id TEXT PRIMARY KEY, anchor_id TEXT NOT NULL,
                    logical_asset_id TEXT, raw_label TEXT NOT NULL,
                    normalized_label TEXT NOT NULL, canonical_concept_id TEXT,
                    concept_aliases_json TEXT NOT NULL, row_order INTEGER NOT NULL,
                    row_path TEXT NOT NULL, row_bbox_json TEXT NOT NULL,
                    report_year TEXT, data_year TEXT, statement_scope TEXT NOT NULL,
                    unit TEXT, currency TEXT, statement_amount_raw TEXT,
                    statement_amount_normalized TEXT, inline_note_reference TEXT,
                    inline_note_reference_evidence_json TEXT NOT NULL,
                    research_definition_id TEXT, definition_version TEXT,
                    producer_version TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(anchor_id,row_order,statement_scope)
                );
                CREATE TABLE IF NOT EXISTS financial_note_indexes (
                    index_id TEXT PRIMARY KEY, source_pdf_sha256 TEXT NOT NULL,
                    source_pdf_id TEXT NOT NULL, index_version TEXT NOT NULL,
                    index_options_json TEXT NOT NULL, producer_version TEXT NOT NULL,
                    notes_start_page INTEGER, notes_end_page INTEGER,
                    index_build_ms REAL NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_pdf_sha256,index_version,index_options_json,producer_version)
                );
                CREATE TABLE IF NOT EXISTS financial_note_headings (
                    heading_id TEXT PRIMARY KEY, index_id TEXT NOT NULL,
                    section_id TEXT, section_type TEXT NOT NULL,
                    raw_heading TEXT NOT NULL, normalized_heading TEXT NOT NULL,
                    heading_level INTEGER NOT NULL, heading_parent_id TEXT,
                    heading_order INTEGER NOT NULL, note_ordinal TEXT,
                    note_reference TEXT, start_page INTEGER NOT NULL,
                    end_page_hint INTEGER, heading_bbox_json TEXT NOT NULL,
                    statement_scope_context TEXT, report_year_context TEXT,
                    unit_context TEXT, text_quality REAL NOT NULL,
                    producer_version TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_note_heading_lookup
                    ON financial_note_headings(index_id,normalized_heading,start_page);
                CREATE TABLE IF NOT EXISTS child_discovery_runs (
                    discovery_run_id TEXT PRIMARY KEY, source_pdf_id TEXT NOT NULL,
                    source_pdf_sha256 TEXT NOT NULL, anchor_id TEXT NOT NULL,
                    anchor_child_id TEXT NOT NULL, requested_scope TEXT NOT NULL,
                    tiers_executed_json TEXT NOT NULL, tiers_skipped_json TEXT NOT NULL,
                    early_stop_reason TEXT, candidate_count_by_tier_json TEXT NOT NULL,
                    runtime_by_tier_json TEXT NOT NULL, metrics_json TEXT NOT NULL,
                    status TEXT NOT NULL, producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS thin_child_table_candidates (
                    candidate_id TEXT PRIMARY KEY, discovery_run_id TEXT NOT NULL,
                    anchor_child_id TEXT NOT NULL, retrieval_tier TEXT NOT NULL,
                    retrieval_method TEXT NOT NULL, retrieval_priority INTEGER NOT NULL,
                    source_pdf_id TEXT NOT NULL, source_pdf_sha256 TEXT NOT NULL,
                    heading_id TEXT NOT NULL, raw_heading TEXT NOT NULL,
                    normalized_heading TEXT NOT NULL, section_id TEXT,
                    section_type TEXT NOT NULL, start_page INTEGER NOT NULL,
                    end_page_hint INTEGER, heading_bbox_json TEXT NOT NULL,
                    note_reference TEXT, statement_scope_hint TEXT,
                    base_score REAL NOT NULL, warning_codes_json TEXT NOT NULL,
                    hard_gate_summary_json TEXT NOT NULL,
                    evidence_ref_ids_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    producer_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidate_evidence (
                    evidence_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
                    evidence_type TEXT NOT NULL, evidence_source TEXT NOT NULL,
                    scalar_value REAL, text_value TEXT, artifact_ref TEXT,
                    bbox_ref TEXT, page_ref TEXT, confidence REAL NOT NULL,
                    producer_version TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS enriched_child_table_candidates (
                    candidate_id TEXT PRIMARY KEY, container_page_range_json TEXT NOT NULL,
                    possible_subtable_roles_json TEXT NOT NULL,
                    scope_evidence_json TEXT NOT NULL, period_evidence_json TEXT NOT NULL,
                    unit_evidence_json TEXT NOT NULL, lightweight_table_presence INTEGER NOT NULL,
                    lightweight_header_signature_json TEXT NOT NULL,
                    lightweight_row_signature_json TEXT NOT NULL,
                    amount_summary_json TEXT NOT NULL,
                    reconciliation_candidates_json TEXT NOT NULL,
                    certification_score REAL NOT NULL, score_breakdown_json TEXT NOT NULL,
                    hard_gate_results_json TEXT NOT NULL,
                    positive_evidence_json TEXT NOT NULL, negative_evidence_json TEXT NOT NULL,
                    enrichment_runtime_ms REAL NOT NULL, enrichment_version TEXT NOT NULL,
                    producer_version TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS child_table_link_candidates (
                    link_candidate_id TEXT PRIMARY KEY, anchor_id TEXT NOT NULL,
                    anchor_child_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                    logical_table_candidate_id TEXT,
                    proposed_member_table_id TEXT NOT NULL,
                    proposed_subtable_role TEXT NOT NULL,
                    proposed_relation_type TEXT NOT NULL,
                    statement_scope TEXT NOT NULL, report_year TEXT,
                    retrieval_prior REAL NOT NULL, evidence_score REAL NOT NULL,
                    penalty_score REAL NOT NULL, certification_score REAL NOT NULL,
                    score_breakdown_json TEXT NOT NULL, hard_gate_results_json TEXT NOT NULL,
                    reconciliation_relation TEXT, reconciliation_status TEXT,
                    confidence REAL NOT NULL, blocking_warnings_json TEXT NOT NULL,
                    ranking_position INTEGER, is_recommended INTEGER NOT NULL,
                    is_preselected INTEGER NOT NULL, producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS global_child_assignments (
                    assignment_id TEXT PRIMARY KEY, anchor_id TEXT NOT NULL,
                    statement_scope TEXT NOT NULL, decisions_json TEXT NOT NULL,
                    conflicts_json TEXT NOT NULL, rejected_links_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL, assignment_runtime_ms REAL NOT NULL,
                    producer_version TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS child_note_table_inventories (
                    note_table_inventory_candidate_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    source_pdf_id TEXT NOT NULL,
                    source_pdf_sha256 TEXT NOT NULL DEFAULT '',
                    note_reference TEXT NOT NULL,
                    note_title TEXT NOT NULL DEFAULT '',
                    scan_start_page INTEGER NOT NULL,
                    scan_end_page INTEGER NOT NULL,
                    next_note_boundary_page INTEGER,
                    scan_scope_json TEXT NOT NULL,
                    logical_table_count INTEGER NOT NULL DEFAULT 0,
                    peer_table_count INTEGER NOT NULL DEFAULT 0,
                    unresolved_table_count INTEGER NOT NULL DEFAULT 0,
                    inventory_status TEXT NOT NULL DEFAULT 'UNRESOLVED',
                    evidence_json TEXT NOT NULL,
                    producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(candidate_id)
                );
                CREATE TABLE IF NOT EXISTS child_logical_table_candidates (
                    logical_table_candidate_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    note_table_inventory_candidate_id TEXT,
                    table_order INTEGER NOT NULL,
                    proposed_classification TEXT NOT NULL,
                    title TEXT NOT NULL,
                    start_page INTEGER NOT NULL,
                    end_page INTEGER NOT NULL,
                    bbox_json TEXT NOT NULL,
                    signature_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(candidate_id,table_order),
                    FOREIGN KEY(note_table_inventory_candidate_id)
                        REFERENCES child_note_table_inventories(
                            note_table_inventory_candidate_id
                        )
                );
                CREATE TABLE IF NOT EXISTS child_table_segment_candidates (
                    segment_candidate_id TEXT PRIMARY KEY,
                    logical_table_candidate_id TEXT NOT NULL,
                    segment_order INTEGER NOT NULL,
                    proposed_classification TEXT NOT NULL,
                    start_page INTEGER NOT NULL,
                    end_page INTEGER NOT NULL,
                    bbox_json TEXT NOT NULL,
                    continuation_of_segment_candidate_id TEXT,
                    period_signature_json TEXT NOT NULL,
                    header_signature_json TEXT NOT NULL,
                    amount_lane_signature_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(logical_table_candidate_id,segment_order),
                    FOREIGN KEY(logical_table_candidate_id)
                        REFERENCES child_logical_table_candidates(
                            logical_table_candidate_id
                        ),
                    FOREIGN KEY(continuation_of_segment_candidate_id)
                        REFERENCES child_table_segment_candidates(
                            segment_candidate_id
                        )
                );
                CREATE INDEX IF NOT EXISTS idx_child_logical_candidates_note
                    ON child_logical_table_candidates(candidate_id,table_order);
                CREATE INDEX IF NOT EXISTS idx_child_inventory_candidates_note
                    ON child_note_table_inventories(
                        source_pdf_id,note_reference,inventory_status
                    );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_child_inventory_candidate
                    ON child_note_table_inventories(candidate_id);
                CREATE INDEX IF NOT EXISTS idx_child_segment_candidates_table_order
                    ON child_table_segment_candidates(
                        logical_table_candidate_id,segment_order
                    );
                CREATE TABLE IF NOT EXISTS certified_note_table_inventories (
                    note_table_inventory_id TEXT PRIMARY KEY,
                    note_table_inventory_candidate_id TEXT,
                    source_pdf_id TEXT NOT NULL,
                    source_pdf_sha256 TEXT NOT NULL DEFAULT '',
                    note_reference TEXT NOT NULL,
                    note_title TEXT NOT NULL DEFAULT '',
                    scan_start_page INTEGER NOT NULL,
                    scan_end_page INTEGER NOT NULL,
                    next_note_boundary_page INTEGER,
                    logical_table_ids_json TEXT NOT NULL,
                    inventory_snapshot_json TEXT NOT NULL,
                    inventory_status TEXT NOT NULL,
                    certification_method TEXT NOT NULL,
                    certification_status TEXT NOT NULL,
                    source_adjudication_id TEXT,
                    reviewer TEXT NOT NULL,
                    certified_at TEXT NOT NULL,
                    producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(note_table_inventory_candidate_id),
                    FOREIGN KEY(note_table_inventory_candidate_id)
                        REFERENCES child_note_table_inventories(
                            note_table_inventory_candidate_id
                        )
                );
                CREATE INDEX IF NOT EXISTS idx_certified_note_inventory_context
                    ON certified_note_table_inventories(
                        source_pdf_id,note_reference,inventory_status,
                        certification_status
                    );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_certified_note_inventory_candidate
                    ON certified_note_table_inventories(
                        note_table_inventory_candidate_id
                    ) WHERE note_table_inventory_candidate_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS certified_child_table_links (
                    certified_link_id TEXT PRIMARY KEY, research_project_id TEXT,
                    research_task_id TEXT, anchor_id TEXT NOT NULL,
                    anchor_child_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                    link_candidate_id TEXT NOT NULL, table_family_id TEXT NOT NULL,
                    member_table_id TEXT NOT NULL, subtable_role TEXT NOT NULL,
                    relation_type TEXT NOT NULL, statement_scope TEXT NOT NULL,
                    report_year TEXT, data_year TEXT, certification_method TEXT NOT NULL,
                    certification_status TEXT NOT NULL, score_snapshot_json TEXT NOT NULL,
                    evidence_snapshot_json TEXT NOT NULL,
                    reconciliation_result_json TEXT NOT NULL,
                    recommended_candidate_id TEXT, selected_candidate_id TEXT NOT NULL,
                    alternative_candidates_json TEXT NOT NULL, reviewer TEXT NOT NULL,
                    certified_at TEXT NOT NULL, research_definition_id TEXT,
                    definition_version TEXT, producer_version TEXT NOT NULL,
                    logical_table_id TEXT NOT NULL DEFAULT '',
                    table_classification TEXT NOT NULL DEFAULT 'PRIMARY_TABLE',
                    segment_manifest_status TEXT NOT NULL
                        DEFAULT 'LEGACY_PRIMARY_ANCHOR_ONLY',
                    note_table_inventory_id TEXT NOT NULL DEFAULT '',
                    note_table_inventory_status TEXT NOT NULL
                        DEFAULT 'LEGACY_UNVERIFIED',
                    logical_table_candidate_id TEXT
                );
                CREATE TABLE IF NOT EXISTS certified_child_table_segments (
                    certified_segment_id TEXT PRIMARY KEY,
                    certified_link_id TEXT NOT NULL,
                    "order" INTEGER NOT NULL,
                    classification TEXT NOT NULL,
                    start_page INTEGER NOT NULL,
                    end_page INTEGER NOT NULL,
                    bbox_json TEXT NOT NULL,
                    continuation_of_segment_id TEXT,
                    header_signature_json TEXT NOT NULL,
                    period_signature_json TEXT NOT NULL,
                    amount_lane_signature_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence_json TEXT NOT NULL,
                    certification_status TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    certified_at TEXT NOT NULL,
                    producer_version TEXT NOT NULL,
                    UNIQUE(certified_link_id,"order"),
                    FOREIGN KEY(certified_link_id)
                        REFERENCES certified_child_table_links(certified_link_id),
                    FOREIGN KEY(continuation_of_segment_id)
                        REFERENCES certified_child_table_segments(certified_segment_id)
                );
                CREATE INDEX IF NOT EXISTS idx_certified_child_segments_link_order
                    ON certified_child_table_segments(certified_link_id,"order");
                CREATE TABLE IF NOT EXISTS child_mapping_review_records (
                    review_record_id TEXT PRIMARY KEY, anchor_child_id TEXT NOT NULL,
                    action TEXT NOT NULL, selected_candidate_id TEXT,
                    rejected_candidates_json TEXT NOT NULL, reason TEXT NOT NULL,
                    reviewer TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    producer_version TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS child_mapping_review_queue (
                    queue_id TEXT PRIMARY KEY, anchor_id TEXT NOT NULL,
                    anchor_child_id TEXT NOT NULL, logical_asset_id TEXT,
                    source_pdf_id TEXT NOT NULL, statement_scope TEXT NOT NULL,
                    resolution_case_id TEXT,
                    status TEXT NOT NULL, primary_review_reason TEXT NOT NULL,
                    candidate_ids_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
                    producer_version TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(anchor_child_id, statement_scope),
                    FOREIGN KEY(resolution_case_id)
                        REFERENCES child_inventory_resolution_cases(
                            resolution_case_id
                        )
                );
                CREATE TABLE IF NOT EXISTS child_inventory_resolution_cases (
                    resolution_case_id TEXT PRIMARY KEY,
                    note_table_inventory_candidate_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    anchor_child_id TEXT NOT NULL,
                    source_pdf_id TEXT NOT NULL,
                    source_pdf_sha256 TEXT NOT NULL,
                    discovery_run_id TEXT NOT NULL,
                    case_status TEXT NOT NULL DEFAULT 'OPEN',
                    resolution_state TEXT NOT NULL DEFAULT 'UNRESOLVED',
                    machine_snapshot_sha256 TEXT NOT NULL,
                    machine_snapshot_json TEXT NOT NULL,
                    allowed_logical_candidate_ids_json TEXT NOT NULL,
                    allowed_segment_candidate_ids_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(note_table_inventory_candidate_id)
                        REFERENCES child_note_table_inventories(
                            note_table_inventory_candidate_id
                        )
                );
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_child_inventory_open_resolution_case
                    ON child_inventory_resolution_cases(
                        note_table_inventory_candidate_id
                    )
                    WHERE case_status='OPEN'
                      AND resolution_state='UNRESOLVED';
                CREATE TABLE IF NOT EXISTS child_inventory_adjudications (
                    adjudication_id TEXT PRIMARY KEY,
                    resolution_case_id TEXT NOT NULL UNIQUE,
                    note_table_inventory_candidate_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    decisions_json TEXT NOT NULL,
                    machine_snapshot_sha256 TEXT NOT NULL,
                    effective_snapshot_sha256 TEXT NOT NULL,
                    effective_snapshot_json TEXT NOT NULL,
                    adjudication_status TEXT NOT NULL,
                    producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(resolution_case_id)
                        REFERENCES child_inventory_resolution_cases(
                            resolution_case_id
                        ),
                    FOREIGN KEY(note_table_inventory_candidate_id)
                        REFERENCES child_note_table_inventories(
                            note_table_inventory_candidate_id
                        )
                );
                CREATE INDEX IF NOT EXISTS idx_child_inventory_adjudication
                    ON child_inventory_adjudications(
                        note_table_inventory_candidate_id,
                        adjudication_status
                    );
                CREATE TABLE IF NOT EXISTS structural_learning_candidates (
                    learning_candidate_id TEXT PRIMARY KEY,
                    source_adjudication_id TEXT NOT NULL UNIQUE,
                    source_pdf_sha256 TEXT NOT NULL,
                    source_discovery_run_id TEXT NOT NULL,
                    learning_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PROPOSED',
                    feature_snapshot_json TEXT NOT NULL,
                    label_snapshot_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    producer_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_adjudication_id)
                        REFERENCES child_inventory_adjudications(
                            adjudication_id
                        )
                );
                CREATE TRIGGER IF NOT EXISTS
                    trg_child_inventory_adjudications_no_update
                    BEFORE UPDATE ON child_inventory_adjudications
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'CHILD_INVENTORY_ADJUDICATION_APPEND_ONLY'
                        );
                    END;
                CREATE TRIGGER IF NOT EXISTS
                    trg_child_inventory_adjudications_no_delete
                    BEFORE DELETE ON child_inventory_adjudications
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'CHILD_INVENTORY_ADJUDICATION_APPEND_ONLY'
                        );
                    END;
                CREATE TRIGGER IF NOT EXISTS
                    trg_structural_learning_candidates_no_update
                    BEFORE UPDATE ON structural_learning_candidates
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'STRUCTURAL_LEARNING_CANDIDATE_APPEND_ONLY'
                        );
                    END;
                CREATE TRIGGER IF NOT EXISTS
                    trg_structural_learning_candidates_no_delete
                    BEFORE DELETE ON structural_learning_candidates
                    BEGIN
                        SELECT RAISE(
                            ABORT,
                            'STRUCTURAL_LEARNING_CANDIDATE_APPEND_ONLY'
                        );
                    END;
                CREATE UNIQUE INDEX IF NOT EXISTS
                    idx_structural_learning_candidate_source
                    ON structural_learning_candidates(
                        source_adjudication_id,learning_type
                    );
                CREATE TABLE IF NOT EXISTS structure_revisions (
                    revision_id TEXT PRIMARY KEY, logical_asset_id TEXT NOT NULL,
                    source_capture_id TEXT NOT NULL, new_capture_id TEXT NOT NULL,
                    table_block_id TEXT, revision_type TEXT NOT NULL, actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS downstream_stale_flags (
                    flag_id TEXT PRIMARY KEY, logical_asset_id TEXT, capture_id TEXT,
                    downstream_type TEXT NOT NULL, downstream_id TEXT,
                    reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'STALE',
                    created_at TEXT NOT NULL, resolved_at TEXT
                );
                """
            )
            # v6.8: orchestration and logical-asset governance are additive.
            # Physical Capture evidence remains immutable on disk.
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS capture_requests (
                    request_id TEXT PRIMARY KEY,
                    request_type TEXT NOT NULL,
                    capture_mode TEXT NOT NULL,
                    research_project_id TEXT,
                    research_task_id TEXT,
                    research_batch_id TEXT,
                    research_definition_id TEXT,
                    definition_version TEXT,
                    table_family_id TEXT,
                    member_table_id TEXT,
                    source_pdf_id TEXT,
                    source_pdf_sha256 TEXT,
                    discovery_strategy_id TEXT,
                    priority INTEGER NOT NULL DEFAULT 100,
                    retry_of_request_id TEXT,
                    producer_version TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'QUEUED',
                    payload_json TEXT NOT NULL,
                    requested_by TEXT,
                    requested_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_capture_requests_status
                    ON capture_requests(status,priority,requested_at);

                CREATE TABLE IF NOT EXISTS capture_request_targets (
                    request_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    certification_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(request_id,target_id),
                    FOREIGN KEY(request_id) REFERENCES capture_requests(request_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS strategy_executions (
                    execution_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    selected_target_id TEXT,
                    abstain_reason TEXT,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY(request_id) REFERENCES capture_requests(request_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS logical_assets (
                    logical_asset_id TEXT PRIMARY KEY,
                    identity_key TEXT NOT NULL UNIQUE,
                    company_id TEXT,
                    filing_type TEXT,
                    report_year TEXT,
                    statement_scope TEXT,
                    research_project_id TEXT,
                    research_task_id TEXT,
                    research_batch_id TEXT,
                    research_definition_id TEXT,
                    definition_version TEXT,
                    table_family_id TEXT,
                    member_table_id TEXT,
                    logical_source_role TEXT,
                    direct_asset_status TEXT NOT NULL DEFAULT 'ACTIVE',
                    archived_by_parent INTEGER NOT NULL DEFAULT 0,
                    identity_confidence REAL,
                    derivation_evidence_json TEXT NOT NULL,
                    current_capture_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_logical_asset_facets
                    ON logical_assets(company_id,report_year,table_family_id,member_table_id,direct_asset_status);

                CREATE TABLE IF NOT EXISTS capture_versions (
                    logical_asset_id TEXT NOT NULL,
                    capture_id TEXT NOT NULL UNIQUE,
                    capture_version INTEGER NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 0,
                    processing_status TEXT NOT NULL DEFAULT 'PENDING',
                    registration_status TEXT NOT NULL DEFAULT 'PENDING',
                    quality_status TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',
                    review_status TEXT NOT NULL DEFAULT 'PENDING',
                    asset_status TEXT NOT NULL DEFAULT 'ACTIVE',
                    supersedes_capture_id TEXT,
                    superseded_by_capture_id TEXT,
                    producer_version TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(logical_asset_id,capture_version),
                    FOREIGN KEY(logical_asset_id) REFERENCES logical_assets(logical_asset_id)
                );
                CREATE INDEX IF NOT EXISTS idx_capture_versions_current
                    ON capture_versions(logical_asset_id,is_current,asset_status);

                CREATE TABLE IF NOT EXISTS asset_status_transitions (
                    transition_id TEXT PRIMARY KEY,
                    logical_asset_id TEXT,
                    capture_id TEXT,
                    previous_status TEXT,
                    new_status TEXT NOT NULL,
                    actor TEXT,
                    reason TEXT,
                    evidence_json TEXT NOT NULL,
                    source_ui_action TEXT,
                    producer_version TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_asset_transition_asset
                    ON asset_status_transitions(logical_asset_id,capture_id,created_at);

                CREATE TABLE IF NOT EXISTS review_queue (
                    review_item_id TEXT PRIMARY KEY,
                    logical_asset_id TEXT NOT NULL,
                    capture_id TEXT NOT NULL UNIQUE,
                    primary_review_reason TEXT NOT NULL,
                    secondary_review_reasons_json TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    recommended_action TEXT,
                    evidence_summary_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_review_queue_default
                    ON review_queue(status,severity,primary_review_reason,updated_at);

                CREATE TABLE IF NOT EXISTS saved_review_views (
                    view_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    owner TEXT,
                    filters_json TEXT NOT NULL,
                    sort_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS saved_asset_views (
                    view_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    owner TEXT,
                    filters_json TEXT NOT NULL,
                    sort_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS archive_operations (
                    operation_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT,
                    reason TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS asset_tags (
                    logical_asset_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(logical_asset_id,tag)
                );
                -- v6.11: Stage B execution context is database state, not
                -- Streamlit session state. Job progress and Review Inbox stay
                -- authoritative in their own tables; this row persists the
                -- stable references needed to reconstruct the workflow.
                CREATE TABLE IF NOT EXISTS stage_b_execution_sessions (
                    session_key TEXT PRIMARY KEY,
                    entry_origin TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    scope TEXT,
                    research_definition_id TEXT,
                    definition_version TEXT,
                    status TEXT NOT NULL,
                    research_batch_id TEXT,
                    plan_ids_json TEXT NOT NULL,
                    batch_ids_json TEXT NOT NULL,
                    callback_key TEXT NOT NULL,
                    workspace_route TEXT NOT NULL,
                    workspace_filter_json TEXT NOT NULL,
                    capture_scope_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_stage_b_execution_research_batch
                    ON stage_b_execution_sessions(research_batch_id);
                """
            )
            logical_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(logical_assets)").fetchall()
            }
            if "research_batch_id" not in logical_columns:
                conn.execute("ALTER TABLE logical_assets ADD COLUMN research_batch_id TEXT")
            stage_b_columns = {
                row[1] for row in conn.execute(
                    "PRAGMA table_info(stage_b_execution_sessions)"
                ).fetchall()
            }
            if "capture_scope_json" not in stage_b_columns:
                conn.execute(
                    "ALTER TABLE stage_b_execution_sessions ADD COLUMN "
                    "capture_scope_json TEXT NOT NULL DEFAULT '{}'"
                )
            certified_link_columns = {
                row[1] for row in conn.execute(
                    "PRAGMA table_info(certified_child_table_links)"
                ).fetchall()
            }
            certified_link_additions = {
                "logical_table_id":"TEXT NOT NULL DEFAULT ''",
                "table_classification":(
                    "TEXT NOT NULL DEFAULT 'PRIMARY_TABLE'"
                ),
                "segment_manifest_status":(
                    "TEXT NOT NULL DEFAULT 'LEGACY_PRIMARY_ANCHOR_ONLY'"
                ),
                "note_table_inventory_id":"TEXT NOT NULL DEFAULT ''",
                "note_table_inventory_status":(
                    "TEXT NOT NULL DEFAULT 'LEGACY_UNVERIFIED'"
                ),
                "logical_table_candidate_id":"TEXT",
            }
            for name,declaration in certified_link_additions.items():
                if name not in certified_link_columns:
                    conn.execute(
                        f"ALTER TABLE certified_child_table_links "
                        f"ADD COLUMN {name} {declaration}"
                    )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS
                   idx_certified_child_links_inventory
                   ON certified_child_table_links(note_table_inventory_id)"""
            )
            child_link_candidate_columns = {
                row[1] for row in conn.execute(
                    "PRAGMA table_info(child_table_link_candidates)"
                ).fetchall()
            }
            if "logical_table_candidate_id" not in child_link_candidate_columns:
                conn.execute(
                    "ALTER TABLE child_table_link_candidates ADD COLUMN "
                    "logical_table_candidate_id TEXT"
                )
            child_logical_candidate_columns = {
                row[1] for row in conn.execute(
                    "PRAGMA table_info(child_logical_table_candidates)"
                ).fetchall()
            }
            if (
                "note_table_inventory_candidate_id"
                not in child_logical_candidate_columns
            ):
                conn.execute(
                    "ALTER TABLE child_logical_table_candidates ADD COLUMN "
                    "note_table_inventory_candidate_id TEXT"
                )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS
                   idx_child_link_candidates_logical_table
                   ON child_table_link_candidates(logical_table_candidate_id)"""
            )
            conn.execute(
                """CREATE INDEX IF NOT EXISTS
                   idx_child_logical_candidates_inventory
                   ON child_logical_table_candidates(
                       note_table_inventory_candidate_id,table_order
                   )"""
            )
            child_mapping_queue_columns = {
                row[1] for row in conn.execute(
                    "PRAGMA table_info(child_mapping_review_queue)"
                ).fetchall()
            }
            if "resolution_case_id" not in child_mapping_queue_columns:
                conn.execute(
                    "ALTER TABLE child_mapping_review_queue ADD COLUMN "
                    "resolution_case_id TEXT"
                )
            certified_inventory_columns = {
                row[1] for row in conn.execute(
                    "PRAGMA table_info(certified_note_table_inventories)"
                ).fetchall()
            }
            if "source_adjudication_id" not in certified_inventory_columns:
                conn.execute(
                    "ALTER TABLE certified_note_table_inventories ADD COLUMN "
                    "source_adjudication_id TEXT"
                )
            conn.execute(
                """UPDATE certified_child_table_links
                   SET logical_table_id=member_table_id
                   WHERE COALESCE(logical_table_id,'')=''"""
            )
            conn.execute(
                """UPDATE certified_child_table_links
                   SET table_classification='PRIMARY_TABLE'
                   WHERE COALESCE(table_classification,'')=''"""
            )
            conn.execute(
                """UPDATE certified_child_table_links
                   SET segment_manifest_status='LEGACY_PRIMARY_ANCHOR_ONLY'
                   WHERE COALESCE(segment_manifest_status,'')=''"""
            )
            conn.execute(
                """UPDATE certified_child_table_links
                   SET note_table_inventory_id=''
                   WHERE note_table_inventory_id IS NULL"""
            )
            conn.execute(
                """UPDATE certified_child_table_links
                   SET note_table_inventory_status='LEGACY_UNVERIFIED'
                   WHERE COALESCE(note_table_inventory_status,'')=''"""
            )
            table_block_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(table_blocks)").fetchall()
            }
            for name in ("classification_axis", "block_terminal_type"):
                if name not in table_block_columns:
                    conn.execute(
                        f"ALTER TABLE table_blocks ADD COLUMN {name} "
                        "TEXT NOT NULL DEFAULT 'UNRESOLVED'"
                    )
            conn.execute(
                """INSERT INTO schema_meta(key,value,updated_at) VALUES('registry_schema_version',?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (str(REGISTRY_SCHEMA_VERSION), now_iso()),
            )

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM schema_meta WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO schema_meta(key,value,updated_at) VALUES(?,?,?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, str(value), now_iso()),
            )

    def event(self, event_type: str, *, asset_type: str = "", asset_id: str = "", payload: Any = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO registry_events(event_type,asset_type,asset_id,payload_json,created_at) VALUES(?,?,?,?,?)",
                (event_type, asset_type, asset_id, _json(payload or {}), now_iso()),
            )

    def upsert_pdf(self, row: dict[str, Any]) -> None:
        now = now_iso()
        values = {
            "pdf_id": str(row.get("pdf_id") or row.get("sha256") or row.get("filename") or row.get("path")),
            "filename": row.get("filename"),
            "display_name": row.get("display_name"),
            "sha256": row.get("sha256"),
            "company": row.get("company"),
            "document_year": str(row.get("document_year") or ""),
            "size_bytes": row.get("size_bytes"),
            "path": row.get("path"),
            "modified_at": row.get("modified_at"),
            "created_at": row.get("created_at") or row.get("modified_at") or now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pdf_assets(pdf_id,filename,display_name,sha256,company,document_year,size_bytes,path,modified_at,created_at,updated_at)
                VALUES(:pdf_id,:filename,:display_name,:sha256,:company,:document_year,:size_bytes,:path,:modified_at,:created_at,:updated_at)
                ON CONFLICT(pdf_id) DO UPDATE SET
                    filename=excluded.filename, display_name=excluded.display_name,
                    sha256=COALESCE(excluded.sha256,pdf_assets.sha256), company=excluded.company,
                    document_year=excluded.document_year, size_bytes=excluded.size_bytes,
                    path=excluded.path, modified_at=excluded.modified_at, updated_at=excluded.updated_at
                """,
                values,
            )

    def upsert_capture(self, row: dict[str, Any]) -> None:
        now = now_iso()
        values = {
            "capture_id": str(row.get("capture_id") or row.get("run_id")),
            "run_path": str(row.get("run_path") or row.get("run_dir")),
            "pdf_id": row.get("pdf_id"),
            "pdf_name": row.get("pdf_name"),
            "source_pdf_display": row.get("source_pdf_display"),
            "company": row.get("company"),
            "document_year": str(row.get("document_year") or ""),
            "table_query": row.get("table_query"),
            "table_family_id": row.get("table_family_id"),
            "schema_variant": row.get("schema_variant"),
            "note_number": str(row.get("note_number") or ""),
            "batch_id": row.get("batch_id"),
            "producer_version": row.get("producer_version"),
            "header_parser": row.get("header_parser"),
            "lifecycle_status": str(row.get("lifecycle_status") or "ACTIVE"),
            "boundary_status": row.get("boundary_status"),
            "header_dimension_status": row.get("header_dimension_status"),
            "merge_ready": 1 if bool(row.get("merge_ready")) else 0,
            "row_count_official": row.get("row_count_official"),
            "invalidation_reason_code": row.get("invalidation_reason_code"),
            "invalidation_note": row.get("invalidation_note"),
            "supersedes_capture_id": row.get("supersedes_capture_id"),
            "superseded_by_capture_id": row.get("superseded_by_capture_id"),
            "is_trashed": 1 if bool(row.get("is_trashed")) or str(row.get("lifecycle_status")) == "TRASHED" else 0,
            "created_at": row.get("created_at") or now,
            "updated_at": now,
        }
        # Ensure batch exists before FK insert.
        if values["batch_id"]:
            self.upsert_batch({"batch_id": values["batch_id"], "updated_at": now})
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO captures(
                    capture_id,run_path,pdf_id,pdf_name,source_pdf_display,company,document_year,
                    table_query,table_family_id,schema_variant,note_number,batch_id,producer_version,
                    header_parser,lifecycle_status,boundary_status,header_dimension_status,merge_ready,
                    row_count_official,invalidation_reason_code,invalidation_note,supersedes_capture_id,
                    superseded_by_capture_id,is_trashed,created_at,updated_at
                ) VALUES(
                    :capture_id,:run_path,:pdf_id,:pdf_name,:source_pdf_display,:company,:document_year,
                    :table_query,:table_family_id,:schema_variant,:note_number,:batch_id,:producer_version,
                    :header_parser,:lifecycle_status,:boundary_status,:header_dimension_status,:merge_ready,
                    :row_count_official,:invalidation_reason_code,:invalidation_note,:supersedes_capture_id,
                    :superseded_by_capture_id,:is_trashed,:created_at,:updated_at
                )
                ON CONFLICT(capture_id) DO UPDATE SET
                    run_path=excluded.run_path, pdf_id=COALESCE(excluded.pdf_id,captures.pdf_id),
                    pdf_name=excluded.pdf_name, source_pdf_display=excluded.source_pdf_display,
                    company=excluded.company, document_year=excluded.document_year,
                    table_query=excluded.table_query, table_family_id=excluded.table_family_id,
                    schema_variant=excluded.schema_variant, note_number=excluded.note_number,
                    batch_id=excluded.batch_id, producer_version=excluded.producer_version,
                    header_parser=excluded.header_parser, lifecycle_status=excluded.lifecycle_status,
                    boundary_status=excluded.boundary_status,
                    header_dimension_status=excluded.header_dimension_status,
                    merge_ready=excluded.merge_ready, row_count_official=excluded.row_count_official,
                    invalidation_reason_code=excluded.invalidation_reason_code,
                    invalidation_note=excluded.invalidation_note,
                    supersedes_capture_id=excluded.supersedes_capture_id,
                    superseded_by_capture_id=excluded.superseded_by_capture_id,
                    is_trashed=excluded.is_trashed, updated_at=excluded.updated_at
                """,
                values,
            )

    def delete_capture(self, capture_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM captures WHERE capture_id=?", (str(capture_id),))

    def upsert_batch(self, row: dict[str, Any]) -> None:
        now = now_iso()
        values = {
            "batch_id": str(row.get("batch_id")),
            "batch_status": str(row.get("batch_status") or "ACTIVE"),
            "table_query": row.get("table_query"),
            "capture_count": int(row.get("capture_count") or 0),
            "active_count": int(row.get("active_count") or row.get("active") or 0),
            "invalidated_count": int(row.get("invalidated_count") or row.get("invalidated") or 0),
            "trashed_count": int(row.get("trashed_count") or row.get("trashed") or 0),
            "producer_versions": row.get("producer_versions"),
            "first_created_at": row.get("first_created_at") or row.get("created_at"),
            "last_created_at": row.get("last_created_at"),
            "updated_at": row.get("updated_at") or now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO capture_batches(batch_id,batch_status,table_query,capture_count,active_count,invalidated_count,trashed_count,producer_versions,first_created_at,last_created_at,updated_at)
                VALUES(:batch_id,:batch_status,:table_query,:capture_count,:active_count,:invalidated_count,:trashed_count,:producer_versions,:first_created_at,:last_created_at,:updated_at)
                ON CONFLICT(batch_id) DO UPDATE SET
                    batch_status=excluded.batch_status, table_query=COALESCE(excluded.table_query,capture_batches.table_query),
                    capture_count=CASE WHEN excluded.capture_count=0 THEN capture_batches.capture_count ELSE excluded.capture_count END,
                    active_count=CASE WHEN excluded.capture_count=0 THEN capture_batches.active_count ELSE excluded.active_count END,
                    invalidated_count=CASE WHEN excluded.capture_count=0 THEN capture_batches.invalidated_count ELSE excluded.invalidated_count END,
                    trashed_count=CASE WHEN excluded.capture_count=0 THEN capture_batches.trashed_count ELSE excluded.trashed_count END,
                    producer_versions=COALESCE(excluded.producer_versions,capture_batches.producer_versions),
                    first_created_at=COALESCE(excluded.first_created_at,capture_batches.first_created_at),
                    last_created_at=COALESCE(excluded.last_created_at,capture_batches.last_created_at), updated_at=excluded.updated_at
                """,
                values,
            )

    def rebuild_batch_summaries(self) -> None:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT batch_id,
                       COUNT(*) AS capture_count,
                       SUM(CASE WHEN lifecycle_status='ACTIVE' AND is_trashed=0 THEN 1 ELSE 0 END) AS active_count,
                       SUM(CASE WHEN lifecycle_status='INVALIDATED' AND is_trashed=0 THEN 1 ELSE 0 END) AS invalidated_count,
                       SUM(CASE WHEN is_trashed=1 OR lifecycle_status='TRASHED' THEN 1 ELSE 0 END) AS trashed_count,
                       MIN(created_at) AS first_created_at,
                       MAX(created_at) AS last_created_at,
                       GROUP_CONCAT(DISTINCT producer_version) AS producer_versions,
                       GROUP_CONCAT(DISTINCT table_query) AS table_queries
                  FROM captures
                 WHERE batch_id IS NOT NULL AND batch_id<>''
                 GROUP BY batch_id
                """
            ).fetchall()
            seen = set()
            for r in rows:
                active, invalidated, trashed = int(r["active_count"] or 0), int(r["invalidated_count"] or 0), int(r["trashed_count"] or 0)
                nontrash = active + invalidated
                if nontrash == 0 and trashed > 0:
                    status = "TRASHED"
                elif active > 0 and invalidated > 0:
                    status = "PARTIALLY_INVALIDATED"
                elif active == 0 and invalidated > 0:
                    status = "FULLY_INVALIDATED"
                else:
                    status = "ACTIVE"
                if trashed > 0 and nontrash > 0:
                    status += "_WITH_TRASHED_ITEMS"
                conn.execute(
                    """
                    INSERT INTO capture_batches(batch_id,batch_status,table_query,capture_count,active_count,invalidated_count,trashed_count,producer_versions,first_created_at,last_created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(batch_id) DO UPDATE SET
                        batch_status=excluded.batch_status,table_query=excluded.table_query,capture_count=excluded.capture_count,
                        active_count=excluded.active_count,invalidated_count=excluded.invalidated_count,trashed_count=excluded.trashed_count,
                        producer_versions=excluded.producer_versions,first_created_at=excluded.first_created_at,
                        last_created_at=excluded.last_created_at,updated_at=excluded.updated_at
                    """,
                    (
                        r["batch_id"], status, r["table_queries"], int(r["capture_count"] or 0), active,
                        invalidated, trashed, r["producer_versions"], r["first_created_at"], r["last_created_at"], now_iso(),
                    ),
                )
                seen.add(str(r["batch_id"]))
            # v6.1 has no independent empty-batch entity. Remove summaries whose
            # last Capture was permanently purged so main/trash views stay exact.
            if seen:
                marks = ",".join("?" for _ in seen)
                conn.execute(f"DELETE FROM capture_batches WHERE batch_id NOT IN ({marks})", tuple(sorted(seen)))
            else:
                conn.execute("DELETE FROM capture_batches")

    def upsert_merge(self, row: dict[str, Any], source_capture_ids: Optional[Iterable[str]] = None) -> None:
        now = now_iso()
        merge_id = str(row.get("merge_id") or row.get("run_id"))
        values = {
            "merge_id": merge_id,
            "run_path": str(row.get("run_path") or row.get("run_dir")),
            "display_name": row.get("display_name"),
            "table_id": row.get("table_id"),
            "source_count": int(row.get("source_count") or 0),
            "lifecycle_status": str(row.get("lifecycle_status") or "ACTIVE"),
            "dependency_status": str(row.get("dependency_status") or "CURRENT"),
            "stale_capture_run_ids_json": _json(row.get("stale_capture_run_ids") or []),
            "created_at": row.get("created_at") or now,
            "updated_at": now,
            "is_trashed": 1 if bool(row.get("is_trashed")) or str(row.get("lifecycle_status")) == "TRASHED" else 0,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO merge_projects(merge_id,run_path,display_name,table_id,source_count,lifecycle_status,dependency_status,stale_capture_run_ids_json,created_at,updated_at,is_trashed)
                VALUES(:merge_id,:run_path,:display_name,:table_id,:source_count,:lifecycle_status,:dependency_status,:stale_capture_run_ids_json,:created_at,:updated_at,:is_trashed)
                ON CONFLICT(merge_id) DO UPDATE SET
                    run_path=excluded.run_path,display_name=excluded.display_name,table_id=excluded.table_id,
                    source_count=excluded.source_count,lifecycle_status=excluded.lifecycle_status,
                    dependency_status=excluded.dependency_status,stale_capture_run_ids_json=excluded.stale_capture_run_ids_json,
                    updated_at=excluded.updated_at,is_trashed=excluded.is_trashed
                """,
                values,
            )
            if source_capture_ids is not None:
                conn.execute("DELETE FROM merge_sources WHERE merge_id=?", (merge_id,))
                for i, capture_id in enumerate(source_capture_ids):
                    conn.execute(
                        "INSERT OR IGNORE INTO merge_sources(merge_id,capture_id,source_order) VALUES(?,?,?)",
                        (merge_id, str(capture_id), i),
                    )
                    conn.execute(
                        """INSERT OR REPLACE INTO asset_dependencies(parent_type,parent_id,child_type,child_id,relation,status,updated_at)
                           VALUES('CAPTURE',?,'MERGE',?,'SOURCE_OF','ACTIVE',?)""",
                        (str(capture_id), merge_id, now),
                    )

    def delete_merge(self, merge_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM merge_projects WHERE merge_id=?", (str(merge_id),))

    def create_job(self, row: dict[str, Any]) -> None:
        now = now_iso()
        values = {
            "job_id": str(row["job_id"]),
            "batch_id": row.get("batch_id"),
            "job_type": str(row.get("job_type") or "GENERIC"),
            "status": str(row.get("status") or "QUEUED"),
            "progress": float(row.get("progress") or 0.0),
            "source_asset_id": row.get("source_asset_id"),
            "target_asset_id": row.get("target_asset_id"),
            "error_type": row.get("error_type"),
            "error_message": row.get("error_message"),
            "payload_json": _json(row.get("payload") or {}),
            "result_json": _json(row.get("result") or {}),
            "created_at": row.get("created_at") or now,
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs(job_id,batch_id,job_type,status,progress,source_asset_id,target_asset_id,error_type,error_message,payload_json,result_json,created_at,started_at,finished_at,updated_at)
                VALUES(:job_id,:batch_id,:job_type,:status,:progress,:source_asset_id,:target_asset_id,:error_type,:error_message,:payload_json,:result_json,:created_at,:started_at,:finished_at,:updated_at)
                ON CONFLICT(job_id) DO UPDATE SET
                    batch_id=excluded.batch_id,job_type=excluded.job_type,status=excluded.status,progress=excluded.progress,
                    source_asset_id=excluded.source_asset_id,target_asset_id=excluded.target_asset_id,error_type=excluded.error_type,
                    error_message=excluded.error_message,payload_json=excluded.payload_json,result_json=excluded.result_json,
                    started_at=excluded.started_at,finished_at=excluded.finished_at,updated_at=excluded.updated_at
                """,
                values,
            )

    def table_counts(self) -> dict[str, int]:
        names = ["pdf_assets", "captures", "capture_batches", "merge_projects", "merge_sources", "jobs"]
        out: dict[str, int] = {}
        with self.connect() as conn:
            for name in names:
                out[name] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"])
        return out
