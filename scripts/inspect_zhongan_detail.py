import fitz
from pathlib import Path

docu = Path(r"C:\dev\AXA_research\docu")

for yr in (2023, 2024, 2025):
    fname = f"众安在线{yr}年度报告.pdf"
    doc = fitz.open(docu / fname)
    print(f"============================== 众安在线 {yr} ({len(doc)} pages) ==============================")
    # Balance Sheet
    for p in range(75, 90):
        txt = doc[p].get_text()
        if "合併資產負債表" in txt or "合併財務狀況表" in txt:
            if "以公允價值計量" in txt or "金融資產" in txt:
                print(f"  [Balance Sheet] Page {p+1}:")
                print(txt[:1000])
                break
    # Notes
    for p in range(120, 160):
        txt = doc[p].get_text()
        if ("以公允價值計量且其變動計入當期損益的金融資產" in txt or "以公允價值計量且其變動計入其他綜合收益的金融資產" in txt or "以攤餘成本計量的金融資產" in txt) and ("股票" in txt or "債券" in txt or "基金" in txt):
            print(f"  [Notes] Page {p+1}:")
            print(txt[:800])
            break
