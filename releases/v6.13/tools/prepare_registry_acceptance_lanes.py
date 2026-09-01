from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _snapshot_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create isolated Offline/UI DATA_HOME metadata snapshots",
    )
    parser.add_argument("--source-data-home", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    source_db = args.source_data_home / "metadata.db"
    if not source_db.is_file():
        raise FileNotFoundError(source_db)

    with sqlite3.connect(
        f"file:{source_db.resolve().as_posix()}?mode=ro", uri=True,
    ) as conn:
        conn.row_factory = sqlite3.Row
        assets = [
            dict(row) for row in conn.execute(
                "SELECT pdf_id,filename,path,lifecycle_status FROM pdf_assets "
                "WHERE lifecycle_status='ACTIVE' ORDER BY filename"
            )
        ]
    manifest = []
    for asset in assets:
        path = Path(str(asset.get("path") or ""))
        manifest.append({
            **asset,
            "exists": path.is_file(),
            "sha256_verified_from_file": _digest(path) if path.is_file() else None,
            "source_access": "READ_ONLY_CANONICAL_REFERENCE",
        })

    for lane_name, invocation in (
        ("offline_lane", "FORMAL_BACKEND_SERVICE_GRAPH"),
        ("ui_lane", "FAKE_STREAMLIT_REAL_PYTHON_ENTRY"),
    ):
        lane = args.output_root / lane_name
        lane.mkdir(parents=True, exist_ok=True)
        _snapshot_database(source_db, lane / "metadata.db")
        (lane / "source_pdf_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        (lane / "lane_state.json").write_text(json.dumps({
            "lane": lane_name,
            "invocation_contract": invocation,
            "metadata_snapshot": str(lane / "metadata.db"),
            "source_data_home": str(args.source_data_home),
            "source_data_home_mutated": False,
            "source_pdf_access": "READ_ONLY_CANONICAL_REFERENCE",
            "execution_status": "NOT_RUN_PENDING_ACCEPTANCE_PREREQUISITES",
            "browser_e2e": "SKIPPED_BY_SCOPE",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "SNAPSHOTS_READY",
        "active_pdf_count": len(manifest),
        "output_root": str(args.output_root),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
