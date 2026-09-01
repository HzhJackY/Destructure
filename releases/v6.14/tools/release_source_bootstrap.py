"""Build/audit a release source tree from a complete reference source tree.

The reference `source_file_manifest.csv` is evidence, never an allow-list.
This tool enumerates the reference tree with explicit release exclusions,
copies only missing allowed files, and emits a reproducible audit manifest.
It deliberately never overwrites target files: version-specific changes need
their own reviewed patch and change record.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


DENY_PARTS = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    "data_home", "data", "golden_corpus", "logs", "output",
}
DENY_SUFFIXES = {".pdf", ".db", ".sqlite", ".sqlite3", ".pyc"}
TRANSIENT_ROOT_FILES = {
    "CURRENT_TASK_ANALYSIS.md",
    "source_file_manifest.csv",
    "reconciliation_summary.json",
    "table_reconciliation_audit.csv",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def is_release_source_file(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if rel.as_posix() in TRANSIENT_ROOT_FILES:
        return False
    if any(part.lower() in DENY_PARTS for part in rel.parts):
        return False
    return path.suffix.lower() not in DENY_SUFFIXES


def source_files(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and is_release_source_file(path, root)
    }


def audit(reference: Path, target: Path) -> dict[str, Any]:
    baseline = source_files(reference)
    missing = sorted(rel for rel in baseline if not (target / rel).is_file())
    matches: list[str] = []
    differs: list[str] = []
    for rel, source in baseline.items():
        destination = target / rel
        if destination.is_file():
            (matches if sha256(source) == sha256(destination) else differs).append(rel)
    return {
        "reference": str(reference),
        "target": str(target),
        "reference_allowed_file_count": len(baseline),
        "missing_allowed_files": missing,
        "matching_hash_files": sorted(matches),
        "different_hash_files": sorted(differs),
    }


def backfill_missing(reference: Path, target: Path) -> dict[str, Any]:
    report = audit(reference, target)
    copied: list[dict[str, str]] = []
    for rel in report["missing_allowed_files"]:
        source = reference / rel
        destination = target / rel
        if destination.exists():
            raise RuntimeError(f"Refusing to overwrite target file: {rel}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if sha256(source) != sha256(destination):
            raise RuntimeError(f"Backfill hash mismatch: {rel}")
        copied.append({"path": rel, "sha256": sha256(destination)})
    return {**audit(reference, target), "copied_missing_files": copied}


def write_manifest(root: Path, destination: Path) -> None:
    rows = [
        {"path": rel, "bytes": path.stat().st_size, "sha256": sha256(path)}
        for rel, path in sorted(source_files(root).items())
    ]
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--backfill-missing", action="store_true")
    parser.add_argument("--strict-baseline", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--write-target-manifest", type=Path)
    args = parser.parse_args()
    if not args.reference.is_dir() or not args.target.is_dir():
        raise SystemExit("reference and target must both be existing directories")
    report = backfill_missing(args.reference, args.target) if args.backfill_missing else audit(args.reference, args.target)
    if args.write_target_manifest:
        write_manifest(args.target, args.write_target_manifest)
        report["target_manifest"] = str(args.write_target_manifest)
    report["strict_baseline_passed"] = not report["missing_allowed_files"] and not report["different_hash_files"]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "missing": len(report["missing_allowed_files"]),
        "copied": len(report.get("copied_missing_files") or []),
        "different_hash_files": len(report["different_hash_files"]),
        "strict_baseline_passed": report["strict_baseline_passed"],
    }, ensure_ascii=False))
    if args.strict_baseline and not report["strict_baseline_passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
