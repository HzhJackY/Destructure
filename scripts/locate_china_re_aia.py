from pathlib import Path
import fitz

DOCU = Path(r"C:\dev\AXA_research\docu")

for filename in ["中国再保2023年年度报告.pdf", "中国再保2024年年度报告.pdf", "中国再保2025年年度报告.pdf", "友邦保险2023年报.pdf", "友邦保险2024年报.pdf", "友邦保险2025年报.pdf"]:
    doc = fitz.open(DOCU / filename)
    print(f"\n=== {filename} ===")
    for p_idx in range(len(doc)):
        txt = doc[p_idx].get_text()
        if any(h in txt for h in ("總投資資產", "总投资资产", "投資資產", "投资资产", "按資產類別", "按资产类别", "按投資品種", "按投资品种", "投資組合", "投资组合", "Financial investments", "Financial assets")) and any(k in txt for k in ("固定收益", "債券", "债券", "定期存款", "股票", "基金", "股權", "股权", "FVTPL", "FVOCI", "AC")):
            for line in txt.splitlines():
                if any(k in line for k in ("按資產類別", "按资产类别", "按投資品種", "按投资品种", "按會計計量", "按会计计量", "投資組合", "投资组合", "投資資產", "投资资产", "總投資資產", "总投资资产")):
                    if len(line.strip()) < 40 and p_idx < 100:
                        print(f"  Page {p_idx+1} (idx {p_idx}): {line.strip()}")
