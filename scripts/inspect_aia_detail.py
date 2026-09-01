import fitz
from pathlib import Path

docu = Path(r"C:\dev\AXA_research\docu")

for yr in (2023, 2024, 2025):
    fname = f"友邦保险{yr}年报.pdf"
    doc = fitz.open(docu / fname)
    print(f"=== AIA {yr} Balance Sheet ===")
    for p in range(145, 175):
        txt = doc[p].get_text()
        if "合併財務狀況表" in txt and "資產" in txt and ("金融投資" in txt or "按公平值" in txt):
            print(f"  Page {p+1} (printed):")
            print(txt[:1000])
            break
    print(f"=== AIA {yr} Note 18 (金融投资) ===")
    for p in range(160, 240):
        txt = doc[p].get_text()
        if ("18. 金融投資" in txt or "18 金融投資" in txt or "18.  金融投資" in txt) and ("債務證券" in txt or "貸款" in txt):
            print(f"  Page {p+1}:")
            print(txt[:1200])
            break
