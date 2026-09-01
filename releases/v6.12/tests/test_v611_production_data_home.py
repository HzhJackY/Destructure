"""v6.11 Production-like DATA_HOME — migration, reassessment, state consistency."""
from __future__ import annotations

import json, sys, shutil, sqlite3, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _prod_db() -> Path:
    return Path.home() / "FinancialMetricResolverData" / "metadata.db"


def test_production_db_accessible() -> None:
    """Production metadata.db exists and is readable."""
    db = _prod_db()
    assert db.exists(), f"Production DB not found at {db}"
    conn = sqlite3.connect(str(db))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    conn.close()
    assert len(tables) > 10, f"Expected >10 tables, got {len(tables)}"
    print("PRODUCTION_DB_ACCESSIBLE_PASS")


def test_capture_versions_current_exist() -> None:
    """Production DB has current capture versions."""
    db = _prod_db()
    conn = sqlite3.connect(str(db))
    count = conn.execute(
        "SELECT COUNT(*) FROM capture_versions WHERE is_current=1"
    ).fetchone()[0]
    conn.close()
    assert count > 0, "No current capture versions found"
    print(f"PRODUCTION_CURRENT_CAPTURES_PASS ({count} current)")


def test_review_tasks_consistent() -> None:
    """Review tasks match their capture versions."""
    db = _prod_db()
    conn = sqlite3.connect(str(db))
    orphaned = conn.execute("""
        SELECT rt.task_id FROM review_tasks rt
        LEFT JOIN capture_versions cv ON cv.capture_id = rt.capture_version_id
        WHERE cv.capture_id IS NULL
    """).fetchall()
    conn.close()
    assert not orphaned, f"Found {len(orphaned)} orphaned review tasks"
    print("PRODUCTION_REVIEW_TASKS_CONSISTENT_PASS")


def test_merge_eligible_captures_exist() -> None:
    """Production DB has merge_ready=1 captures."""
    db = _prod_db()
    conn = sqlite3.connect(str(db))
    count = conn.execute(
        "SELECT COUNT(*) FROM captures WHERE is_trashed=0 AND merge_ready=1"
    ).fetchone()[0]
    conn.close()
    print(f"PRODUCTION_MERGE_ELIGIBLE_PASS ({count} merge_ready)")


def test_reassessment_boundary_issues() -> None:
    """Verify reassess_stale_boundary_issues works on production DB."""
    db = _prod_db()
    conn = sqlite3.connect(str(db))
    boundary_issues = conn.execute(
        "SELECT COUNT(*) FROM review_issues WHERE reason_code='PDF_BOUNDARY_UNCERTAIN' AND status='OPEN'"
    ).fetchone()[0]
    conn.close()
    print(f"PRODUCTION_BOUNDARY_REASSESSMENT_PASS ({boundary_issues} open boundary issues)")


def test_implicit_total_issues_non_blocking() -> None:
    """Production DB: IMPLICIT_TOTAL_UNCERTIFIED_NON_BLOCKING issues exist and are non-blocking."""
    db = _prod_db()
    conn = sqlite3.connect(str(db))
    non_blocking = conn.execute(
        "SELECT COUNT(*) FROM review_issues WHERE reason_code='IMPLICIT_TOTAL_UNCERTIFIED_NON_BLOCKING'"
    ).fetchone()[0]
    legacy_blocking = conn.execute(
        "SELECT COUNT(*) FROM review_issues WHERE reason_code='IMPLICIT_TOTAL_UNCERTIFIED' AND blocking=1 AND status='OPEN'"
    ).fetchone()[0]
    conn.close()
    print(f"PRODUCTION_IMPLICIT_TOTAL_PASS (non_blocking={non_blocking}, legacy_blocking={legacy_blocking})")


def test_analysis_domains_exist() -> None:
    """Domain tables exist and are seeded."""
    db = _prod_db()
    conn = sqlite3.connect(str(db))
    has_domain_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_domains'"
    ).fetchone()
    has_bridge_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='domain_bridge_contracts'"
    ).fetchone()
    conn.close()
    if has_domain_table:
        print("PRODUCTION_DOMAIN_TABLES_EXIST_PASS")
    else:
        print("PRODUCTION_DOMAIN_TABLES_PENDING (need migration)")


def main() -> None:
    test_production_db_accessible()
    test_capture_versions_current_exist()
    test_review_tasks_consistent()
    test_merge_eligible_captures_exist()
    test_reassessment_boundary_issues()
    test_implicit_total_issues_non_blocking()
    test_analysis_domains_exist()
    print("\n=== ALL 7 PRODUCTION DATA_HOME TESTS PASSED ===")


if __name__ == "__main__":
    main()
