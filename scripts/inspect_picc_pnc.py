import fitz
from pathlib import Path

docu = Path(r"C:\dev\AXA_research\docu")

for yr in (2023, 2024, 2025):
    fname = f"中国财险{yr}年度报告.pdf"
    doc = fitz.open(docu / fname)
    print(f"============================== 中国财险 {yr} ({len(doc)} pages) ==============================")
    # Balance Sheet
    for p in range(90, 130):
        txt = doc[p].get_text()
        if "合併財務狀況表" in txt or "合并财务状况表" in txt:
            if "以公允價值計量" in txt or "以公允价值计量" in txt or "按公平值" in txt:
                print(f"  [Balance Sheet] Page {p+1}:")
                print(txt[:1200])
                break
    # MD&A
    for p in range(15, 35):
        txt = doc[p].get_text()
        if "投資資產構成" in txt or "按投資對象分類" in txt or "按會計計量分類" in txt:
            print(f"  [MD&A] Page {p+1}:")
            print(txt[:1000])
