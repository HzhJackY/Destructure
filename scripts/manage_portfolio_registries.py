import csv
from pathlib import Path

root = Path(r"C:\dev\AXA_research\golden_corpus\v1.1.0")
reg_path = root / "investment_portfolio_golden_registry.csv"
ext_reg_path = root / "extended_investment_portfolio_golden_registry.csv"

# 12 Baseline rows
baseline_12_ids = {
    "PING_AN_2023_INVESTMENT_PORTFOLIO", "PING_AN_2024_INVESTMENT_PORTFOLIO", "PING_AN_2025_INVESTMENT_PORTFOLIO",
    "CHINA_LIFE_2023_INVESTMENT_PORTFOLIO", "CHINA_LIFE_2024_INVESTMENT_PORTFOLIO", "CHINA_LIFE_2025_INVESTMENT_PORTFOLIO",
    "CPIC_GROUP_2023_INVESTMENT_PORTFOLIO", "CPIC_GROUP_2024_INVESTMENT_PORTFOLIO", "CPIC_GROUP_2025_INVESTMENT_PORTFOLIO",
    "NEW_CHINA_LIFE_2023_INVESTMENT_PORTFOLIO", "NEW_CHINA_LIFE_2024_INVESTMENT_PORTFOLIO", "NEW_CHINA_LIFE_2025_INVESTMENT_PORTFOLIO"
}

with reg_path.open(encoding="utf-8") as f:
    all_rows = list(csv.DictReader(f))

baseline_rows = [r for r in all_rows if r["golden_id"] in baseline_12_ids]
fieldnames = list(all_rows[0].keys())

with reg_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(baseline_rows)

with ext_reg_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(all_rows)

print(f"BASELINE REGISTRY RESTORED TO {len(baseline_rows)} ROWS; EXTENDED REGISTRY HAS {len(all_rows)} ROWS.")
