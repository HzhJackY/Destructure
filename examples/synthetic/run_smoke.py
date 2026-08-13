#!/usr/bin/env python3
"""Run the redistributable empty-DATA_HOME public smoke check."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[2]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from data_home import ensure_data_home  # noqa: E402
from metadata_registry import MetadataRegistry  # noqa: E402


SMOKE_CONTRACT = "public-synthetic-empty-data-home-v1"


def build_summary() -> dict[str, Any]:
    """Initialize a temporary empty DATA_HOME and return stable status only."""
    bundled_rules = APP_ROOT / "metric_aliases.json"
    with tempfile.TemporaryDirectory(prefix="axa-public-smoke-") as temp_dir:
        data_home = Path(temp_dir) / "data_home"
        started_empty = not data_home.exists()
        paths = ensure_data_home(data_home, bundled_rules)
        registry = MetadataRegistry(paths["metadata_db"])

        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        counts = registry.table_counts()
        required_assets = {
            "manifest": paths["manifest"].is_file(),
            "metadata_db": paths["metadata_db"].is_file(),
            "rules": paths["rules"].is_file(),
            "taxonomy": paths["taxonomy"].is_file(),
        }
        empty_registry = all(count == 0 for count in counts.values())
        ready = started_empty and all(required_assets.values()) and empty_registry

        return {
            "business_records_created": 0,
            "data_home_started_empty": started_empty,
            "data_schema_version": str(manifest.get("data_schema_version") or ""),
            "fictional_fixture": True,
            "network_used": False,
            "pipelines_invoked": [],
            "registry_schema_version": str(
                registry.get_meta("registry_schema_version", "") or ""
            ),
            "registry_table_counts": counts,
            "required_assets": required_assets,
            "smoke_contract": SMOKE_CONTRACT,
            "status": "PASS" if ready else "FAIL",
        }


def main() -> int:
    summary = build_summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

