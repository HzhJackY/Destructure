import csv
from pathlib import Path

csv_path = Path(r"C:\dev\AXA_research\golden_corpus\v1.1.0\investment_portfolio_golden_registry.csv")

with csv_path.open(encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

existing_ids = {r["golden_id"] for r in rows}

new_entries = [
    # PICC
    ("PICC_2023_INVESTMENT_PORTFOLIO", "PICC", "中国人保", "2023", "companies/picc/2023/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P23 independently verified."),
    ("PICC_2024_INVESTMENT_PORTFOLIO", "PICC", "中国人保", "2024", "companies/picc/2024/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P23 independently verified."),
    ("PICC_2025_INVESTMENT_PORTFOLIO", "PICC", "中国人保", "2025", "companies/picc/2025/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P23 independently verified."),
    # PICC P&C
    ("PICC_PNC_2023_INVESTMENT_PORTFOLIO", "PICC_PNC", "中国财险", "2023", "companies/picc_pnc/2023/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P25 independently verified."),
    ("PICC_PNC_2024_INVESTMENT_PORTFOLIO", "PICC_PNC", "中国财险", "2024", "companies/picc_pnc/2024/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P23 independently verified."),
    ("PICC_PNC_2025_INVESTMENT_PORTFOLIO", "PICC_PNC", "中国财险", "2025", "companies/picc_pnc/2025/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P21 independently verified."),
    # China Re
    ("CHINA_RE_2023_INVESTMENT_PORTFOLIO", "CHINA_RE", "中国再保", "2023", "companies/china_re/2023/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P51 independently verified."),
    ("CHINA_RE_2024_INVESTMENT_PORTFOLIO", "CHINA_RE", "中国再保", "2024", "companies/china_re/2024/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P51 independently verified."),
    ("CHINA_RE_2025_INVESTMENT_PORTFOLIO", "CHINA_RE", "中国再保", "2025", "companies/china_re/2025/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P49 independently verified."),
    # Sunshine
    ("SUNSHINE_INSURANCE_2023_INVESTMENT_PORTFOLIO", "SUNSHINE_INSURANCE", "阳光保险", "2023", "companies/sunshine_insurance/2023/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P51 independently verified."),
    ("SUNSHINE_INSURANCE_2024_INVESTMENT_PORTFOLIO", "SUNSHINE_INSURANCE", "阳光保险", "2024", "companies/sunshine_insurance/2024/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P49 independently verified."),
    ("SUNSHINE_INSURANCE_2025_INVESTMENT_PORTFOLIO", "SUNSHINE_INSURANCE", "阳光保险", "2025", "companies/sunshine_insurance/2025/investment_portfolio_golden.yaml", "DIRECT_SEPARATE_TABLES_SAME_PAGE", "2", "2", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P44 independently verified."),
    # ZhongAn
    ("ZHONGAN_ONLINE_2023_INVESTMENT_PORTFOLIO", "ZHONGAN_ONLINE", "众安在线", "2023", "companies/zhongan_online/2023/investment_portfolio_golden.yaml", "DIRECT_SINGLE_AXIS_TABLE", "1", "1", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P33 independently verified."),
    ("ZHONGAN_ONLINE_2024_INVESTMENT_PORTFOLIO", "ZHONGAN_ONLINE", "众安在线", "2024", "companies/zhongan_online/2024/investment_portfolio_golden.yaml", "DIRECT_SINGLE_AXIS_TABLE", "1", "1", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P32 independently verified."),
    ("ZHONGAN_ONLINE_2025_INVESTMENT_PORTFOLIO", "ZHONGAN_ONLINE", "众安在线", "2025", "companies/zhongan_online/2025/investment_portfolio_golden.yaml", "DIRECT_SINGLE_AXIS_TABLE", "1", "1", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P28 independently verified."),
    # AIA
    ("AIA_2023_INVESTMENT_PORTFOLIO", "AIA", "友邦保险", "2023", "companies/aia/2023/investment_portfolio_golden.yaml", "DIRECT_SINGLE_AXIS_TABLE", "1", "1", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P42 independently verified."),
    ("AIA_2024_INVESTMENT_PORTFOLIO", "AIA", "友邦保险", "2024", "companies/aia/2024/investment_portfolio_golden.yaml", "DIRECT_SINGLE_AXIS_TABLE", "1", "1", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P45 independently verified."),
    ("AIA_2025_INVESTMENT_PORTFOLIO", "AIA", "友邦保险", "2025", "companies/aia/2025/investment_portfolio_golden.yaml", "DIRECT_SINGLE_AXIS_TABLE", "1", "1", "DISCLOSED", "FULL", "CERTIFIED_GOLDEN_ROW_VALUES", "Codex_Agent_Adjudicator", "2026-08-23", "Direct PDF native text on P44 independently verified."),
]

fieldnames = list(rows[0].keys())

for item in new_entries:
    if item[0] not in existing_ids:
        rows.append(dict(zip(fieldnames, item)))

with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"PORTFOLIO REGISTRY UPDATED WITH {len(rows)} TOTAL ENTRIES!")
