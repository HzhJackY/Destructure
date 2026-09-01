import csv
from pathlib import Path

root = Path(r"C:\dev\AXA_research\golden_corpus\v1.1.0")

# 1. Update golden_coverage_registry.csv for CPIC
cov_path = root / "golden_coverage_registry.csv"
with cov_path.open(encoding="utf-8") as f:
    cov_rows = list(csv.DictReader(f))

for r in cov_rows:
    if r["filing_id"] == "CPIC_2023":
        r["main_statement_value_assertion_count"] = "4"
        r["primary_child_table_count"] = "0"
        r["primary_child_value_assertion_count"] = "0"
        r["current_period_value_assertion_count"] = "4"
        r["comparative_period_value_assertion_count"] = "0"
        r["evidence_crops_status"] = "NOT_REQUIRED"
    elif r["filing_id"] == "CPIC_2024":
        r["main_statement_value_assertion_count"] = "4"
        r["primary_child_table_count"] = "0"
        r["primary_child_value_assertion_count"] = "0"
        r["current_period_value_assertion_count"] = "4"
        r["comparative_period_value_assertion_count"] = "0"
        r["evidence_crops_status"] = "NOT_REQUIRED"
    elif r["filing_id"] == "CPIC_2025":
        r["main_statement_value_assertion_count"] = "4"
        r["primary_child_table_count"] = "0"
        r["primary_child_value_assertion_count"] = "0"
        r["current_period_value_assertion_count"] = "4"
        r["comparative_period_value_assertion_count"] = "0"
        r["evidence_crops_status"] = "NOT_REQUIRED"

with cov_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(cov_rows[0].keys()))
    writer.writeheader()
    writer.writerows(cov_rows)

# 2. Update golden_table_segment_registry.csv to remove outdated CPIC child segment rows
seg_path = root / "golden_table_segment_registry.csv"
with seg_path.open(encoding="utf-8") as f:
    seg_rows = list(csv.DictReader(f))

new_seg_rows = [r for r in seg_rows if not r["filing_id"].startswith("CPIC_")]

with seg_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(seg_rows[0].keys()))
    writer.writeheader()
    writer.writerows(new_seg_rows)

print("COVERAGE & SEGMENT REGISTRIES RECONCILED!")
