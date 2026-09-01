from pathlib import Path
import fitz

DOCU = Path(r"C:\dev\AXA_research\docu")

FILINGS = [
    # PICC (中国人保)
    ("中国人保", "picc", 2023, "中国人保2023年年度报告.pdf", 142),
    ("中国人保", "picc", 2024, "中国人保2024年年度报告.pdf", 142),
    ("中国人保", "picc", 2025, "中国人保2025年年度报告.pdf", 127),

    # China Re (中国再保)
    ("中国再保", "china_re", 2023, "中国再保2023年年度报告.pdf", 179),
    ("中国再保", "china_re", 2024, "中国再保2024年年度报告.pdf", 178),
    ("中国再保", "china_re", 2025, "中国再保2025年年度报告.pdf", 176),

    # Sunshine Insurance (阳光保险)
    ("阳光保险", "sunshine_insurance", 2023, "阳光保险2023年度报告.pdf", 175),
    ("阳光保险", "sunshine_insurance", 2024, "阳光保险2024年度报告.pdf", 170),
    ("阳光保险", "sunshine_insurance", 2025, "阳光保险2025年度报告.pdf", 157),

    # ZhongAn Online (众安在线)
    ("众安在线", "zhongan_online", 2023, "众安在线2023年度报告.pdf", 84),
    ("众安在线", "zhongan_online", 2024, "众安在线2024年度报告.pdf", 83),
    ("众安在线", "zhongan_online", 2025, "众安在线2025年度报告.pdf", 80),

    # AIA (友邦保险)
    ("友邦保险", "aia", 2023, "友邦保险2023年报.pdf", 190),
    ("友邦保险", "aia", 2024, "友邦保险2024年报.pdf", 195),
    ("友邦保险", "aia", 2025, "友邦保险2025年报.pdf", 183),

    # PICC P&C (中国财险)
    ("中国财险", "picc_pnc", 2023, "中国财险2023年度报告.pdf", 168),
    ("中国财险", "picc_pnc", 2024, "中国财险2024年度报告.pdf", 158),
    ("中国财险", "picc_pnc", 2025, "中国财险2025年度报告.pdf", 151),
]

for comp_name, comp_id, year, filename, page_1based in FILINGS:
    doc = fitz.open(DOCU / filename)
    txt = doc[page_1based - 1].get_text()
    print(f"\n==================== {comp_name} ({comp_id}) {year} Page {page_1based} ====================")
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    for l in lines[:35]:
        print(" ", l)
