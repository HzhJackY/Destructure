from pathlib import Path
import fitz
import json

DOCU = Path(r"C:\dev\AXA_research\docu")

FILES = [
    # PICC
    ("中国人保", "picc", 2023, "中国人保2023年年度报告.pdf"),
    ("中国人保", "picc", 2024, "中国人保2024年年度报告.pdf"),
    ("中国人保", "picc", 2025, "中国人保2025年年度报告.pdf"),

    # PICC P&C
    ("中国财险", "picc_pnc", 2023, "中国财险2023年度报告.pdf"),
    ("中国财险", "picc_pnc", 2024, "中国财险2024年度报告.pdf"),
    ("中国财险", "picc_pnc", 2025, "中国财险2025年度报告.pdf"),

    # China Re
    ("中国再保", "china_re", 2023, "中国再保2023年年度报告.pdf"),
    ("中国再保", "china_re", 2024, "中国再保2024年年度报告.pdf"),
    ("中国再保", "china_re", 2025, "中国再保2025年年度报告.pdf"),

    # Sunshine
    ("阳光保险", "sunshine_insurance", 2023, "阳光保险2023年度报告.pdf"),
    ("阳光保险", "sunshine_insurance", 2024, "阳光保险2024年度报告.pdf"),
    ("阳光保险", "sunshine_insurance", 2025, "阳光保险2025年度报告.pdf"),

    # ZhongAn
    ("众安在线", "zhongan_online", 2023, "众安在线2023年度报告.pdf"),
    ("众安在线", "zhongan_online", 2024, "众安在线2024年度报告.pdf"),
    ("众安在线", "zhongan_online", 2025, "众安在线2025年度报告.pdf"),

    # AIA
    ("友邦保险", "aia", 2023, "友邦保险2023年报.pdf"),
    ("友邦保险", "aia", 2024, "友邦保险2024年报.pdf"),
    ("友邦保险", "aia", 2025, "友邦保险2025年报.pdf"),
]

for cname, cid, year, filename in FILES:
    doc = fitz.open(DOCU / filename)
    print(f"\n=== {cname} {year} ({filename}) ===")
    for p_idx in range(min(120, len(doc))):
        txt = doc[p_idx].get_text()
        if ("投资资产" in txt or "投資資產" in txt or "投资组合" in txt or "投資組合" in txt or "金融投资" in txt) and ("按投资品种" in txt or "按投資品種" in txt or "按会计计量" in txt or "按會計計量" in txt or "固定收益类" in txt or "固定收益類" in txt or "债券投资" in txt or "債券投資" in txt or "按資產類別" in txt):
            # Check if this page contains portfolio table
            for line in txt.splitlines():
                if any(h in line for h in ("投资组合", "投資組合", "投资资产", "投資資產", "按投资品种", "按投資品種", "按会计计量", "按會計計量", "资产配置", "資產配置")):
                    if len(line.strip()) < 50:
                        print(f"  Page {p_idx+1} (idx {p_idx}): {line.strip()}")
