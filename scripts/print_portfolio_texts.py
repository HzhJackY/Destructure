from pathlib import Path
import fitz

DOCU = Path(r"C:\dev\AXA_research\docu")

PORTFOLIO_PAGES = [
    ("中国人保", "picc", 2023, "中国人保2023年年度报告.pdf", 23),
    ("中国人保", "picc", 2024, "中国人保2024年年度报告.pdf", 23),
    ("中国人保", "picc", 2025, "中国人保2025年年度报告.pdf", 23),

    ("中国财险", "picc_pnc", 2023, "中国财险2023年度报告.pdf", 25),
    ("中国财险", "picc_pnc", 2024, "中国财险2024年度报告.pdf", 23),
    ("中国财险", "picc_pnc", 2025, "中国财险2025年度报告.pdf", 21),

    ("中国再保", "china_re", 2023, "中国再保2023年年度报告.pdf", 51),
    ("中国再保", "china_re", 2024, "中国再保2024年年度报告.pdf", 51),
    ("中国再保", "china_re", 2025, "中国再保2025年年度报告.pdf", 49),

    ("阳光保险", "sunshine_insurance", 2023, "阳光保险2023年度报告.pdf", 51),
    ("阳光保险", "sunshine_insurance", 2024, "阳光保险2024年度报告.pdf", 49),
    ("阳光保险", "sunshine_insurance", 2025, "阳光保险2025年度报告.pdf", 44),

    ("众安在线", "zhongan_online", 2023, "众安在线2023年度报告.pdf", 33),
    ("众安在线", "zhongan_online", 2024, "众安在线2024年度报告.pdf", 32),
    ("众安在线", "zhongan_online", 2025, "众安在线2025年度报告.pdf", 28),

    ("友邦保险", "aia", 2023, "友邦保险2023年报.pdf", 42),
    ("友邦保险", "aia", 2024, "友邦保险2024年报.pdf", 45),
    ("友邦保险", "aia", 2025, "友邦保险2025年报.pdf", 44),
]

for cname, cid, year, filename, p_num in PORTFOLIO_PAGES:
    doc = fitz.open(DOCU / filename)
    txt = doc[p_num - 1].get_text()
    print(f"\n==================== {cname} ({cid}) {year} Page {p_num} ====================")
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    for l in lines:
        print(" ", l)
