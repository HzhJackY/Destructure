import fitz
from pathlib import Path

docu = Path(r"C:\dev\AXA_research\docu")

# 1. China Re (中国再保)
for yr in (2023, 2024, 2025):
    fname = f"中国再保{yr}年年度报告.pdf"
    doc = fitz.open(docu / fname)
    print(f"============================== 中国再保 {yr} ({len(doc)} pages) ==============================")
    # Balance Sheet
    for p in range(145, 175):
        txt = doc[p].get_text()
        if "合併財務狀況表" in txt or "合并资产负债表" in txt:
            print(f"  [Balance Sheet] Page {p+1}:")
            for l in txt.splitlines()[:25]:
                if any(k in l for k in ("單位", "单位", "以公允", "以攤餘", "以摊余", "資產總計", "資產總額", "12月31日", "附註")):
                    print(f"    {l.strip()}")
    # MD&A
    for p in range(40, 60):
        txt = doc[p].get_text()
        if "總投資資產的組合構成" in txt or "总投资资产的组合构成" in txt or "投資組合" in txt:
            print(f"  [MD&A Portfolio] Page {p+1}:")
            for l in txt.splitlines()[:30]:
                print(f"    {l.strip()}")

# 2. ZhongAn Online (众安在线)
for yr in (2023, 2024, 2025):
    fname = f"众安在线{yr}年度报告.pdf"
    doc = fitz.open(docu / fname)
    print(f"============================== 众安在线 {yr} ({len(doc)} pages) ==============================")
    # Balance Sheet
    for p in range(70, 95):
        txt = doc[p].get_text()
        if "合併資產負債表" in txt or "合并资产负债表" in txt or "合併財務狀況表" in txt:
            if "以公允價值計量" in txt:
                print(f"  [Balance Sheet] Page {p+1}:")
                for l in txt.splitlines()[:25]:
                    if any(k in l for k in ("千元", "百萬元", "人民幣", "以公允", "以攤餘", "以摊余", "資產總計", "資產總額", "12月31日", "附註")):
                        print(f"    {l.strip()}")
    # MD&A
    for p in range(20, 40):
        txt = doc[p].get_text()
        if "投資資產構成" in txt or "保險資金投資組合" in txt or "境內保險資金投資組合" in txt:
            print(f"  [MD&A Portfolio] Page {p+1}:")
            for l in txt.splitlines()[:30]:
                print(f"    {l.strip()}")
