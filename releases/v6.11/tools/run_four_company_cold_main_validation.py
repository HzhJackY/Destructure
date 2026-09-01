"""Cold-run main-statement validation after four-company child-cache reset."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run_12_filing_matrix import run_matrix

OUT = Path(r"C:\dev\AXA_research\output\_agent_runs\four_company_child_cache_reset")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = run_matrix(
        run_mode="REAL_COLD_RUN",
        cache_dir_override=OUT / "cold_index_cache",
    )
    (OUT / "main_statement_cold_matrix.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (OUT / "main_statement_cold_matrix.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)
    passed = sum(row.get("family_resolution") == "PASS" for row in rows)
    print(f"MAIN_STATEMENT_COLD_PASS={passed}/{len(rows)}")


if __name__ == "__main__":
    main()
