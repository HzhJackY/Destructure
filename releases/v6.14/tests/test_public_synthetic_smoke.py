from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "synthetic" / "run_smoke.py"
EXPECTED = ROOT / "examples" / "synthetic" / "expected_summary.json"


def test_public_synthetic_smoke_matches_expected_empty_state() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    actual = json.loads(completed.stdout)
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))

    assert actual == expected
    assert actual["status"] == "PASS"
    assert actual["business_records_created"] == 0
    assert all(value == 0 for value in actual["registry_table_counts"].values())
    assert actual["pipelines_invoked"] == []
    assert actual["network_used"] is False

