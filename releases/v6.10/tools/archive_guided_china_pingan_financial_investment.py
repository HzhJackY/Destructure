"""Archive and clear the China Ping An / 金融投资 guided-capture history.

The operation is intentionally narrow: it leaves PDF assets untouched, writes a
restorable database snapshot, moves only guided plan/capture output folders into
the archive, and then removes the corresponding UI history from metadata.db.
Run with --dry-run first; --execute performs the change.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DATA_HOME = Path(r"C:\Users\HzhJa\FinancialMetricResolverData")
DB_PATH = DATA_HOME / "metadata.db"
FAMILY = "金融投资"
COMPANY_TOKEN = "中国平安"


def rows(conn: sqlite3.Connection, sql: str, parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, tuple(parameters)).fetchall()]


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values) or "NULL"


def select_scope(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    conn.row_factory = sqlite3.Row
    pdf_assets = rows(
        conn,
        "SELECT * FROM pdf_assets WHERE company LIKE ? AND document_year IN ('2023','2024','2025')",
        (f"%{COMPANY_TOKEN}%",),
    )
    # The older guided workflow persisted the physical source path as pdf_id in
    # its operational tables, whereas PDF Registry uses PDF::<normalized path>.
    # Keep the two identities distinct and join guided history by source path.
    pdf_paths = [r["path"] for r in pdf_assets]
    if not pdf_paths:
        return {"pdf_assets": []}
    pdf_marks = placeholders(pdf_paths)
    plans = rows(
        conn,
        f"SELECT * FROM capture_plans WHERE table_family=? AND pdf_id IN ({pdf_marks})",
        [FAMILY, *pdf_paths],
    )
    plan_ids = [r["plan_id"] for r in plans]
    plan_items = rows(
        conn,
        f"SELECT * FROM capture_plan_items WHERE plan_id IN ({placeholders(plan_ids)})",
        plan_ids,
    ) if plan_ids else []

    # Guided jobs must identify both the selected PDF and the table family.  The
    # payload test avoids deleting any manual/advanced capture that happens to
    # have the same query text.
    jobs = rows(
        conn,
        """
        SELECT * FROM jobs
        WHERE batch_id LIKE 'GUIDED_%'
          AND payload_json LIKE ?
          AND payload_json LIKE ?
        """,
        (f"%{COMPANY_TOKEN}%", f"%{FAMILY}%"),
    )
    job_batch_ids = {r["batch_id"] for r in jobs if r.get("batch_id")}
    captures = rows(
        conn,
        f"""
        SELECT * FROM captures
        WHERE pdf_id IN ({pdf_marks})
          AND table_family_id=?
        """,
        [*pdf_paths, FAMILY],
    )
    batch_ids = sorted(job_batch_ids | {r["batch_id"] for r in captures if r.get("batch_id")})
    capture_ids = [r["capture_id"] for r in captures]
    semantics = rows(
        conn,
        f"SELECT * FROM capture_semantics WHERE capture_id IN ({placeholders(capture_ids)})",
        capture_ids,
    ) if capture_ids else []
    batches = rows(
        conn,
        f"SELECT * FROM capture_batches WHERE batch_id IN ({placeholders(batch_ids)})",
        batch_ids,
    ) if batch_ids else []

    occurrences = rows(
        conn,
        f"""
        SELECT * FROM statement_occurrences
        WHERE pdf_id IN ({pdf_marks}) AND display_name=? AND table_family=?
        """,
        [*pdf_paths, FAMILY, FAMILY],
    )
    occurrence_ids = [r["occurrence_id"] for r in occurrences]
    anchor_actions = rows(
        conn,
        f"SELECT * FROM anchor_adjudications WHERE occurrence_id IN ({placeholders(occurrence_ids)})",
        occurrence_ids,
    ) if occurrence_ids else []
    discoveries = rows(
        conn,
        f"""
        SELECT * FROM machine_discoveries
        WHERE pdf_id IN ({pdf_marks}) AND display_name=? AND table_family=?
        """,
        [*pdf_paths, FAMILY, FAMILY],
    )
    discovery_ids = [r["discovery_id"] for r in discoveries]
    discovery_actions = rows(conn, f"SELECT * FROM discovery_adjudications WHERE discovery_id IN ({placeholders(discovery_ids)})", discovery_ids) if discovery_ids else []
    certified = rows(conn, f"SELECT * FROM certified_discoveries WHERE discovery_id IN ({placeholders(discovery_ids)})", discovery_ids) if discovery_ids else []
    training = rows(conn, f"SELECT * FROM discovery_training_examples WHERE discovery_id IN ({placeholders(discovery_ids)})", discovery_ids) if discovery_ids else []
    locator_training = rows(conn, f"SELECT * FROM note_locator_training_examples WHERE discovery_id IN ({placeholders(discovery_ids)})", discovery_ids) if discovery_ids else []
    clusters = rows(
        conn,
        """SELECT * FROM discovery_candidate_clusters
           WHERE normalized_company LIKE ? AND display_name=?
             AND report_year IN ('2023','2024','2025')""",
        (f"%{COMPANY_TOKEN}%", FAMILY),
    )
    asset_ids = plan_ids + capture_ids + batch_ids + occurrence_ids + discovery_ids
    events = rows(conn, f"SELECT * FROM registry_events WHERE asset_id IN ({placeholders(asset_ids)})", asset_ids) if asset_ids else []
    return {
        "pdf_assets": pdf_assets,
        "capture_plans": plans, "capture_plan_items": plan_items,
        "jobs": jobs, "capture_batches": batches, "captures": captures,
        "capture_semantics": semantics, "statement_occurrences": occurrences,
        "anchor_adjudications": anchor_actions, "machine_discoveries": discoveries,
        "discovery_adjudications": discovery_actions, "certified_discoveries": certified,
        "discovery_training_examples": training,
        "note_locator_training_examples": locator_training,
        "discovery_candidate_clusters": clusters, "registry_events": events,
    }


def ids(scope: dict[str, list[dict[str, Any]]], table: str, column: str) -> list[str]:
    return [str(r[column]) for r in scope.get(table, []) if r.get(column)]


def delete_where(conn: sqlite3.Connection, table: str, column: str, values: list[str]) -> None:
    if values:
        conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders(values)})", values)


def move_if_exists(source: Path, destination_root: Path) -> str | None:
    if not source.exists():
        return None
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / source.name
    if destination.exists():
        raise RuntimeError(f"archive collision: {destination}")
    shutil.move(str(source), str(destination))
    return str(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="perform the archive and database cleanup")
    args = parser.parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = DATA_HOME / "archive" / f"guided_china_pingan_financial_investment_{timestamp}"
    with sqlite3.connect(DB_PATH) as conn:
        scope = select_scope(conn)
        counts = {name: len(value) for name, value in scope.items()}
        print(json.dumps({"mode": "execute" if args.execute else "dry_run", "counts": counts}, ensure_ascii=False, indent=2))
        if not args.execute:
            return 0
        archive_dir.mkdir(parents=True, exist_ok=False)
        (archive_dir / "database_snapshot.json").write_text(json.dumps(scope, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        moved: list[dict[str, str]] = []
        # File output is moved before metadata commit; an exception rolls the
        # moved paths back to their original folder.
        try:
            for row in scope["captures"]:
                source = Path(row["run_path"])
                target = move_if_exists(source, archive_dir / "capture_outputs")
                if target:
                    moved.append({"from": str(source), "to": target})
            for plan_id in ids(scope, "capture_plans", "plan_id"):
                source = DATA_HOME / "table_captures" / "guided_capture_plans" / plan_id
                target = move_if_exists(source, archive_dir / "guided_capture_plans")
                if target:
                    moved.append({"from": str(source), "to": target})

            conn.execute("BEGIN")
            delete_where(conn, "registry_events", "event_id", ids(scope, "registry_events", "event_id"))
            delete_where(conn, "capture_semantics", "capture_id", ids(scope, "captures", "capture_id"))
            delete_where(conn, "captures", "capture_id", ids(scope, "captures", "capture_id"))
            delete_where(conn, "jobs", "job_id", ids(scope, "jobs", "job_id"))
            delete_where(conn, "capture_batches", "batch_id", ids(scope, "capture_batches", "batch_id"))
            delete_where(conn, "capture_plan_items", "plan_id", ids(scope, "capture_plans", "plan_id"))
            delete_where(conn, "capture_plans", "plan_id", ids(scope, "capture_plans", "plan_id"))
            delete_where(conn, "anchor_adjudications", "action_id", ids(scope, "anchor_adjudications", "action_id"))
            delete_where(conn, "statement_occurrences", "occurrence_id", ids(scope, "statement_occurrences", "occurrence_id"))
            delete_where(conn, "discovery_adjudications", "action_id", ids(scope, "discovery_adjudications", "action_id"))
            delete_where(conn, "certified_discoveries", "certified_id", ids(scope, "certified_discoveries", "certified_id"))
            delete_where(conn, "discovery_training_examples", "example_id", ids(scope, "discovery_training_examples", "example_id"))
            delete_where(conn, "note_locator_training_examples", "example_id", ids(scope, "note_locator_training_examples", "example_id"))
            delete_where(conn, "machine_discoveries", "discovery_id", ids(scope, "machine_discoveries", "discovery_id"))
            delete_where(conn, "discovery_candidate_clusters", "cluster_id", ids(scope, "discovery_candidate_clusters", "cluster_id"))
            conn.commit()
        except Exception:
            conn.rollback()
            for entry in reversed(moved):
                target, source = Path(entry["to"]), Path(entry["from"])
                if target.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(target), str(source))
            raise
    (archive_dir / "archive_manifest.json").write_text(json.dumps({"scope": "中国平安 2023–2025 / 金融投资 / Research-Guided Capture", "moved": moved}, ensure_ascii=False, indent=2), encoding="utf-8")
    (archive_dir / "RESTORE.md").write_text("已归档而非删除。恢复时请先停止应用，再将对应目录移回 table_captures，并从 database_snapshot.json 由受控恢复脚本恢复数据库记录。原始 PDF assets 未被移动或删除。\n", encoding="utf-8")
    print(f"ARCHIVED_AND_CLEARED={archive_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
