"""Archive and remove stale four-company financial-investment child history.

This is a controlled DATA_HOME maintenance utility.  It never touches source
PDF assets or Golden assets.  It copies every selected SQLite record into a
timestamped archive, moves source-index cache entries into that archive, then
removes only operational Child-discovery/capture state so fresh Stage A/B work
cannot reuse stale candidates or failed cache runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_home import resolve_data_home

COMPANIES = ("中国平安", "新华保险", "中国太保", "中国太平洋", "中国人寿")
FAMILY_VALUES = ("金融投资", "financial_investment")
DOCU = Path(r"C:\dev\AXA_research\docu")
FILINGS = (
    "中国平安2023年报.pdf", "中国平安2024年报.pdf", "中国平安2025年报.pdf",
    "新华保险2023年报.pdf", "新华保险2024年报.pdf", "新华保险2025年报.pdf",
    "中国太保2023年报.pdf", "中国太保2024年报.pdf", "中国太保2025年报.pdf",
    "中国人寿2023年年度报告.pdf", "中国人寿2024年年度报告.pdf", "中国人寿2025年年度报告.pdf",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def placeholders(values: Iterable[Any]) -> str:
    values = list(values)
    return ",".join("?" for _ in values) or "NULL"


def fetch(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def ids(rows: list[dict[str, Any]], key: str) -> list[str]:
    return [str(row[key]) for row in rows if row.get(key) not in (None, "")]


def matching_paths(conn: sqlite3.Connection, shas: list[str]) -> set[str]:
    paths = {str((DOCU / name).resolve()) for name in FILINGS}
    columns = {row[1] for row in conn.execute("PRAGMA table_info(pdf_assets)")}
    if {"path", "sha256"}.issubset(columns):
        for row in conn.execute(
            f"SELECT path FROM pdf_assets WHERE sha256 IN ({placeholders(shas)})", shas
        ):
            paths.add(str(row[0]))
    return paths


def scope(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    conn.row_factory = sqlite3.Row
    filing_paths = [str((DOCU / name).resolve()) for name in FILINGS]
    shas = [sha256(DOCU / name) for name in FILINGS]
    source_ids = matching_paths(conn, shas) | set(filing_paths)
    years = ("2023", "2024", "2025")
    company_clause = " OR ".join("company LIKE ?" for _ in COMPANIES)
    occurrence_sql = f"""
        SELECT * FROM statement_occurrences
        WHERE table_family IN ({placeholders(FAMILY_VALUES)})
          AND report_year IN ({placeholders(years)})
          AND ({company_clause} OR pdf_id IN ({placeholders(source_ids)}))
    """
    occurrences = fetch(
        conn,
        occurrence_sql,
        [*FAMILY_VALUES, *years, *[f"%{x}%" for x in COMPANIES], *source_ids],
    )
    occurrence_ids = ids(occurrences, "occurrence_id")

    # Stage-B operational facts are source-SHA based.  This deliberately
    # catches paths imported under opaque PDF identifiers.
    runs = fetch(
        conn,
        f"SELECT * FROM child_discovery_runs WHERE source_pdf_sha256 IN ({placeholders(shas)})",
        shas,
    )
    anchor_ids = set(occurrence_ids) | {str(row["anchor_id"]) for row in runs if row.get("anchor_id")}
    children = fetch(
        conn,
        f"SELECT * FROM anchor_child_concepts WHERE anchor_id IN ({placeholders(anchor_ids)})",
        list(anchor_ids),
    ) if anchor_ids else []
    child_ids = set(ids(children, "anchor_child_id")) | {str(row["anchor_child_id"]) for row in runs if row.get("anchor_child_id")}
    if child_ids:
        extra_runs = fetch(conn, f"SELECT * FROM child_discovery_runs WHERE anchor_child_id IN ({placeholders(child_ids)})", list(child_ids))
        runs_by_id = {row["discovery_run_id"]: row for row in [*runs, *extra_runs]}
        runs = list(runs_by_id.values())
    run_ids = ids(runs, "discovery_run_id")
    candidates = fetch(conn, f"SELECT * FROM thin_child_table_candidates WHERE discovery_run_id IN ({placeholders(run_ids)})", run_ids) if run_ids else []
    candidate_ids = ids(candidates, "candidate_id")

    links = fetch(
        conn,
        f"SELECT * FROM child_table_link_candidates WHERE anchor_child_id IN ({placeholders(child_ids)}) OR candidate_id IN ({placeholders(candidate_ids)})",
        [*child_ids, *candidate_ids],
    ) if (child_ids or candidate_ids) else []
    link_ids = ids(links, "link_candidate_id")
    certified_links = fetch(
        conn,
        f"SELECT * FROM certified_child_table_links WHERE anchor_child_id IN ({placeholders(child_ids)}) OR candidate_id IN ({placeholders(candidate_ids)}) OR link_candidate_id IN ({placeholders(link_ids)})",
        [*child_ids, *candidate_ids, *link_ids],
    ) if (child_ids or candidate_ids or link_ids) else []

    index_rows = fetch(conn, f"SELECT * FROM financial_note_indexes WHERE source_pdf_sha256 IN ({placeholders(shas)})", shas)
    index_ids = ids(index_rows, "index_id")
    note_containers = fetch(conn, f"SELECT * FROM note_containers WHERE source_pdf_sha256 IN ({placeholders(shas)})", shas)
    edges = fetch(conn, f"SELECT * FROM statement_note_edges WHERE pdf_id IN ({placeholders(source_ids)})", list(source_ids)) if source_ids else []
    note_targets = fetch(conn, f"SELECT * FROM certified_note_targets WHERE occurrence_id IN ({placeholders(occurrence_ids)})", occurrence_ids) if occurrence_ids else []
    scores = fetch(conn, f"SELECT * FROM anchor_candidate_scores WHERE occurrence_id IN ({placeholders(occurrence_ids)})", occurrence_ids) if occurrence_ids else []
    anchor_audits = fetch(conn, f"SELECT * FROM anchor_certification_audit WHERE occurrence_id IN ({placeholders(occurrence_ids)})", occurrence_ids) if occurrence_ids else []
    anchor_actions = fetch(conn, f"SELECT * FROM anchor_adjudications WHERE occurrence_id IN ({placeholders(occurrence_ids)})", occurrence_ids) if occurrence_ids else []
    global_assignments = fetch(conn, f"SELECT * FROM global_child_assignments WHERE anchor_id IN ({placeholders(anchor_ids)})", list(anchor_ids)) if anchor_ids else []
    mapping_queue = fetch(conn, f"SELECT * FROM child_mapping_review_queue WHERE anchor_child_id IN ({placeholders(child_ids)})", list(child_ids)) if child_ids else []
    mapping_records = fetch(conn, f"SELECT * FROM child_mapping_review_records WHERE anchor_child_id IN ({placeholders(child_ids)})", list(child_ids)) if child_ids else []
    anchor_queue = fetch(conn, f"SELECT * FROM anchor_review_queue WHERE source_pdf_id IN ({placeholders(source_ids)})", list(source_ids)) if source_ids else []

    # Guided capture artifacts are operational history, not source evidence.
    captures = fetch(
        conn,
        f"SELECT * FROM captures WHERE pdf_id IN ({placeholders(source_ids)}) AND table_family_id IN ({placeholders(FAMILY_VALUES)})",
        [*source_ids, *FAMILY_VALUES],
    ) if source_ids else []
    capture_ids = ids(captures, "capture_id")
    batch_ids = {str(row["batch_id"]) for row in captures if row.get("batch_id")}
    plans = fetch(
        conn,
        f"SELECT * FROM capture_plans WHERE pdf_id IN ({placeholders(source_ids)}) AND table_family IN ({placeholders(FAMILY_VALUES)})",
        [*source_ids, *FAMILY_VALUES],
    ) if source_ids else []
    plan_ids = ids(plans, "plan_id")
    jobs = fetch(conn, f"SELECT * FROM jobs WHERE batch_id IN ({placeholders(batch_ids)})", list(batch_ids)) if batch_ids else []
    requests = fetch(conn, f"SELECT * FROM capture_requests WHERE source_pdf_sha256 IN ({placeholders(shas)}) AND table_family_id IN ({placeholders(FAMILY_VALUES)})", [*shas, *FAMILY_VALUES])
    request_ids = ids(requests, "request_id")
    batch_members = fetch(conn, f"SELECT * FROM research_batch_members WHERE research_batch_id IN (SELECT DISTINCT research_batch_id FROM capture_requests WHERE request_id IN ({placeholders(request_ids)}))", request_ids) if request_ids else []
    batch_ids_from_requests = sorted({str(row.get("research_batch_id")) for row in requests if row.get("research_batch_id")})
    research_batches = fetch(conn, f"SELECT * FROM research_batches WHERE research_batch_id IN ({placeholders(batch_ids_from_requests)})", batch_ids_from_requests) if batch_ids_from_requests else []

    return {
        "filings": [{"filename": name, "sha256": digest} for name, digest in zip(FILINGS, shas)],
        "statement_occurrences": occurrences,
        "anchor_child_concepts": children,
        "child_discovery_runs": runs,
        "thin_child_table_candidates": candidates,
        "candidate_evidence": fetch(conn, f"SELECT * FROM candidate_evidence WHERE candidate_id IN ({placeholders(candidate_ids)})", candidate_ids) if candidate_ids else [],
        "enriched_child_table_candidates": fetch(conn, f"SELECT * FROM enriched_child_table_candidates WHERE candidate_id IN ({placeholders(candidate_ids)})", candidate_ids) if candidate_ids else [],
        "child_table_link_candidates": links,
        "certified_child_table_links": certified_links,
        "child_mapping_review_queue": mapping_queue,
        "child_mapping_review_records": mapping_records,
        "global_child_assignments": global_assignments,
        "financial_note_indexes": index_rows,
        "financial_note_headings": fetch(conn, f"SELECT * FROM financial_note_headings WHERE index_id IN ({placeholders(index_ids)})", index_ids) if index_ids else [],
        "note_containers": note_containers,
        "statement_note_edges": edges,
        "certified_note_targets": note_targets,
        "anchor_candidate_scores": scores,
        "anchor_certification_audit": anchor_audits,
        "anchor_adjudications": anchor_actions,
        "anchor_review_queue": anchor_queue,
        "captures": captures,
        "capture_versions": fetch(conn, f"SELECT * FROM capture_versions WHERE capture_id IN ({placeholders(capture_ids)})", capture_ids) if capture_ids else [],
        "capture_semantics": fetch(conn, f"SELECT * FROM capture_semantics WHERE capture_id IN ({placeholders(capture_ids)})", capture_ids) if capture_ids else [],
        "table_notes": fetch(conn, f"SELECT * FROM table_notes WHERE capture_id IN ({placeholders(capture_ids)})", capture_ids) if capture_ids else [],
        "capture_bundle_children": fetch(conn, f"SELECT * FROM capture_bundle_children WHERE capture_id IN ({placeholders(capture_ids)})", capture_ids) if capture_ids else [],
        "capture_plans": plans,
        "capture_plan_items": fetch(conn, f"SELECT * FROM capture_plan_items WHERE plan_id IN ({placeholders(plan_ids)})", plan_ids) if plan_ids else [],
        "jobs": jobs,
        "capture_batches": fetch(conn, f"SELECT * FROM capture_batches WHERE batch_id IN ({placeholders(batch_ids)})", list(batch_ids)) if batch_ids else [],
        "capture_requests": requests,
        "capture_request_targets": fetch(conn, f"SELECT * FROM capture_request_targets WHERE request_id IN ({placeholders(request_ids)})", request_ids) if request_ids else [],
        "research_batch_members": batch_members,
        "research_batches": research_batches,
    }


def delete_by_ids(conn: sqlite3.Connection, table: str, column: str, values: list[str]) -> None:
    # SQLite's parameter ceiling is much lower than a filing-wide note index
    # (which can contain tens of thousands of headings).  Chunking keeps the
    # same enclosing transaction and prevents a partial data-governance run.
    for offset in range(0, len(values), 500):
        chunk = values[offset:offset + 500]
        conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders(chunk)})", chunk)


def move(path: Path, root: Path, moved: list[dict[str, str]]) -> None:
    if not path.exists():
        return
    root.mkdir(parents=True, exist_ok=True)
    destination = root / path.name
    if destination.exists():
        raise RuntimeError(f"archive collision: {destination}")
    shutil.move(str(path), str(destination))
    moved.append({"from": str(path), "to": str(destination)})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    data_home = resolve_data_home(ROOT)
    db = data_home / "metadata.db"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = data_home / "archive" / f"four_company_child_history_{timestamp}"
    with sqlite3.connect(db) as conn:
        scope_rows = scope(conn)
    counts = {key: len(value) for key, value in scope_rows.items() if isinstance(value, list)}
    print(json.dumps({"mode": "execute" if args.execute else "dry_run", "data_home": str(data_home), "counts": counts}, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0
    archive.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(db) as source, sqlite3.connect(archive / "metadata_before.sqlite") as backup:
        source.backup(backup)
    (archive / "database_snapshot.json").write_text(json.dumps(scope_rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    moved: list[dict[str, str]] = []
    target_shas = [row["sha256"] for row in scope_rows["filings"]]
    try:
        for digest in target_shas:
            move(data_home / "cache" / digest, archive / "cache", moved)
            prefix = digest[:24]
            move(data_home / "cache" / "statement_indexes" / f"{prefix}.statement_text_index.json", archive / "statement_indexes", moved)
        for row in scope_rows["captures"]:
            if row.get("run_path"):
                move(Path(str(row["run_path"])), archive / "capture_outputs", moved)
        for plan_id in ids(scope_rows["capture_plans"], "plan_id"):
            move(data_home / "table_captures" / "guided_capture_plans" / plan_id, archive / "guided_capture_plans", moved)
        with sqlite3.connect(db) as conn:
            conn.execute("BEGIN")
            # Child discovery and immutable machine results, most dependent first.
            delete_by_ids(conn, "candidate_evidence", "candidate_id", ids(scope_rows["thin_child_table_candidates"], "candidate_id"))
            delete_by_ids(conn, "enriched_child_table_candidates", "candidate_id", ids(scope_rows["thin_child_table_candidates"], "candidate_id"))
            delete_by_ids(conn, "certified_child_table_links", "certified_link_id", ids(scope_rows["certified_child_table_links"], "certified_link_id"))
            delete_by_ids(conn, "child_table_link_candidates", "link_candidate_id", ids(scope_rows["child_table_link_candidates"], "link_candidate_id"))
            delete_by_ids(conn, "child_mapping_review_records", "review_record_id", ids(scope_rows["child_mapping_review_records"], "review_record_id"))
            delete_by_ids(conn, "child_mapping_review_queue", "queue_id", ids(scope_rows["child_mapping_review_queue"], "queue_id"))
            delete_by_ids(conn, "global_child_assignments", "assignment_id", ids(scope_rows["global_child_assignments"], "assignment_id"))
            delete_by_ids(conn, "thin_child_table_candidates", "candidate_id", ids(scope_rows["thin_child_table_candidates"], "candidate_id"))
            delete_by_ids(conn, "child_discovery_runs", "discovery_run_id", ids(scope_rows["child_discovery_runs"], "discovery_run_id"))
            delete_by_ids(conn, "anchor_child_concepts", "anchor_child_id", ids(scope_rows["anchor_child_concepts"], "anchor_child_id"))
            # Child-navigation caches and current note targets.
            delete_by_ids(conn, "financial_note_headings", "heading_id", ids(scope_rows["financial_note_headings"], "heading_id"))
            delete_by_ids(conn, "financial_note_indexes", "index_id", ids(scope_rows["financial_note_indexes"], "index_id"))
            delete_by_ids(conn, "note_containers", "container_id", ids(scope_rows["note_containers"], "container_id"))
            delete_by_ids(conn, "statement_note_edges", "edge_id", ids(scope_rows["statement_note_edges"], "edge_id"))
            delete_by_ids(conn, "certified_note_targets", "note_target_id", ids(scope_rows["certified_note_targets"], "note_target_id"))
            # Reset machine occurrence state too: a repeated occurrence is not a
            # source PDF fact, and leaving it active would reintroduce duplicate
            # Stage-A lanes after the Child reset.
            delete_by_ids(conn, "anchor_candidate_scores", "score_id", ids(scope_rows["anchor_candidate_scores"], "score_id"))
            delete_by_ids(conn, "anchor_certification_audit", "audit_id", ids(scope_rows["anchor_certification_audit"], "audit_id"))
            delete_by_ids(conn, "anchor_adjudications", "action_id", ids(scope_rows["anchor_adjudications"], "action_id"))
            delete_by_ids(conn, "anchor_review_queue", "anchor_review_item_id", ids(scope_rows["anchor_review_queue"], "anchor_review_item_id"))
            # Historical guided Capture operational records.
            delete_by_ids(conn, "capture_bundle_children", "capture_id", ids(scope_rows["captures"], "capture_id"))
            delete_by_ids(conn, "table_notes", "note_id", ids(scope_rows["table_notes"], "note_id"))
            delete_by_ids(conn, "capture_semantics", "capture_id", ids(scope_rows["captures"], "capture_id"))
            delete_by_ids(conn, "capture_versions", "capture_id", ids(scope_rows["captures"], "capture_id"))
            delete_by_ids(conn, "captures", "capture_id", ids(scope_rows["captures"], "capture_id"))
            delete_by_ids(conn, "capture_request_targets", "target_id", ids(scope_rows["capture_request_targets"], "target_id"))
            delete_by_ids(conn, "capture_requests", "request_id", ids(scope_rows["capture_requests"], "request_id"))
            delete_by_ids(conn, "research_batch_members", "research_batch_id", ids(scope_rows["research_batches"], "research_batch_id"))
            delete_by_ids(conn, "research_batches", "research_batch_id", ids(scope_rows["research_batches"], "research_batch_id"))
            delete_by_ids(conn, "capture_plan_items", "item_id", ids(scope_rows["capture_plan_items"], "item_id"))
            delete_by_ids(conn, "capture_plans", "plan_id", ids(scope_rows["capture_plans"], "plan_id"))
            delete_by_ids(conn, "jobs", "job_id", ids(scope_rows["jobs"], "job_id"))
            delete_by_ids(conn, "capture_batches", "batch_id", ids(scope_rows["capture_batches"], "batch_id"))
            # The PDF is the immutable source.  Occurrences are cacheable machine
            # interpretations, so reset them together with their stale child graph.
            delete_by_ids(conn, "statement_occurrences", "occurrence_id", ids(scope_rows["statement_occurrences"], "occurrence_id"))
            conn.commit()
    except Exception:
        for entry in reversed(moved):
            src, dst = Path(entry["from"]), Path(entry["to"])
            if dst.exists() and not src.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(src))
        raise
    (archive / "archive_manifest.json").write_text(json.dumps({"scope": "four companies / 2023-2025 / financial-investment child history", "moved": moved, "counts": counts}, ensure_ascii=False, indent=2), encoding="utf-8")
    (archive / "RESTORE.md").write_text("本次操作隔离了主表 occurrence、Child 发现、候选、认证链接、附注索引、相关引导抓取作业和缓存；原始 PDF 与 Golden 未移动或删除。恢复请停止应用后由 metadata_before.sqlite 或 database_snapshot.json 进行受控恢复，并将对应 cache/capture 路径移回。\n", encoding="utf-8")
    print(f"ARCHIVED_AND_CLEARED={archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
