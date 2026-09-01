import fitz
from pathlib import Path

docu = Path(r"C:\dev\AXA_research\docu")

for yr in (2023, 2024, 2025):
    fname = f"友邦保险{yr}年报.pdf"
    doc = fitz.open(docu / fname)
    print(f"============================== 友邦保险 {yr} ({len(doc)} pages) ==============================")
    # Balance Sheet
    for p in range(145, 175):
        txt = doc[p].get_text()
        if "合併財務狀況表" in txt or "合併資產負債表" in txt or "合并资产负债表" in txt:
            if "金融投資" in txt or "金融投资" in txt:
                print(f"  [Balance Sheet] Page {p+1}:")
                print(txt[:1200])
                break
    # MD&A
    for p in range(35, 55):
        txt = doc[p].get_text()
        if "總投資" in txt or "总投资" in txt or "投資組合" in txt:
            if "保單持有人及股東" in txt or "保单持有人及股东" in txt or "單位連結式" in txt or "单位连结式" in txt:
                print(f"  [MD&A] Page {p+1}:")
                print(txt[:1000])
