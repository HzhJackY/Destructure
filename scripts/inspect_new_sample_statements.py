from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import fitz
import re
import json

DOCU = Path(r"C:\dev\AXA_research\docu")

FILES = [
    # PICC (中国人保)
    {"company": "中国人保", "company_id": "picc", "year": 2023, "pdf": "中国人保2023年年度报告.pdf"},
    {"company": "中国人保", "company_id": "picc", "year": 2024, "pdf": "中国人保2024年年度报告.pdf"},
    {"company": "中国人保", "company_id": "picc", "year": 2025, "pdf": "中国人保2025年年度报告.pdf"},

    # PICC P&C (中国财险)
    {"company": "中国财险", "company_id": "picc_pnc", "year": 2023, "pdf": "中国财险2023年度报告.pdf"},
    {"company": "中国财险", "company_id": "picc_pnc", "year": 2024, "pdf": "中国财险2024年度报告.pdf"},
    {"company": "中国财险", "company_id": "picc_pnc", "year": 2025, "pdf": "中国财险2025年度报告.pdf"},

    # China Re (中国再保)
    {"company": "中国再保", "company_id": "china_re", "year": 2023, "pdf": "中国再保2023年年度报告.pdf"},
    {"company": "中国再保", "company_id": "china_re", "year": 2024, "pdf": "中国再保2024年年度报告.pdf"},
    {"company": "中国再保", "company_id": "china_re", "year": 2025, "pdf": "中国再保2025年年度报告.pdf"},

    # Sunshine Insurance (阳光保险)
    {"company": "阳光保险", "company_id": "sunshine_insurance", "year": 2023, "pdf": "阳光保险2023年度报告.pdf"},
    {"company": "阳光保险", "company_id": "sunshine_insurance", "year": 2024, "pdf": "阳光保险2024年度报告.pdf"},
    {"company": "阳光保险", "company_id": "sunshine_insurance", "year": 2025, "pdf": "阳光保险2025年度报告.pdf"},

    # ZhongAn Online (众安在线)
    {"company": "众安在线", "company_id": "zhongan_online", "year": 2023, "pdf": "众安在线2023年度报告.pdf"},
    {"company": "众安在线", "company_id": "zhongan_online", "year": 2024, "pdf": "众安在线2024年度报告.pdf"},
    {"company": "众安在线", "company_id": "zhongan_online", "year": 2025, "pdf": "众安在线2025年度报告.pdf"},

    # AIA (友邦保险)
    {"company": "友邦保险", "company_id": "aia", "year": 2023, "pdf": "友邦保险2023年报.pdf"},
    {"company": "友邦保险", "company_id": "aia", "year": 2024, "pdf": "友邦保险2024年报.pdf"},
    {"company": "友邦保险", "company_id": "aia", "year": 2025, "pdf": "友邦保险2025年报.pdf"},
]

results = []

for item in FILES:
    pdf_path = DOCU / item["pdf"]
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    
    # 1. Locate Consolidated Balance Sheet
    bs_candidates = []
    for p_idx in range(total_pages):
        text = doc[p_idx].get_text()
        first_1000 = text[:1000]
        # Look for balance sheet keywords in Chinese or English
        is_bs = False
        if any(h in first_1000 for h in ("合并资产负债表", "CONSOLIDATED STATEMENT OF FINANCIAL POSITION", "合并财务状况表")):
            is_bs = True
        elif "资产负债表" in first_1000 and any(k in text for k in ("交易性金融资产", "金融投资", "债权投资", "定期存款", "货币资金")):
            is_bs = True
            
        if is_bs:
            # Check if it has assets
            has_assets = any(k in text for k in ("流动资产", "资产", "交易性金融资产", "金融资产", "债权投资", "定期存款", "货币资金", "ASSETS"))
            if has_assets:
                bs_candidates.append(p_idx)

    # Prefer the first one or consolidated one
    bs_page_idx = bs_candidates[0] if bs_candidates else None
    
    bs_text = ""
    printed_page = ""
    unit = "人民币百万元"
    if bs_page_idx is not None:
        bs_text = doc[bs_page_idx].get_text()
        for line in bs_text.splitlines()[:15]:
            if "单位" in line or "百万元" in line or "千元" in line or "百万美元" in line or "RMB" in line or "USD" in line:
                unit = line.strip()
            if re.match(r"^\d{1,3}$", line.strip()):
                printed_page = line.strip()
                
    h = sha256(pdf_path.read_bytes()).hexdigest()
    
    print(f"=== {item['company']} {item['year']} ({item['pdf']}) ===")
    print(f"  Pages: {total_pages}, Size: {pdf_path.stat().st_size}, SHA: {h[:16]}...")
    print(f"  Balance sheet page candidates (0-based): {bs_candidates} (1-based: {[x+1 for x in bs_candidates]})")
    print(f"  Unit line: {unit}")
    
    # Print key rows
    if bs_page_idx is not None:
        print(f"  --- Balance sheet preview (Page {bs_page_idx+1}) ---")
        for line in bs_text.splitlines():
            if any(term in line for term in ("交易性金融资产", "债权投资", "其他债权投资", "其他权益工具投资", "以公允价值", "定期存款", "可供出售", "持有至到期", "金融投资", "投资资产", "Financial investments", "Financial assets")):
                print(f"    {line.strip()}")

    results.append({
        "company": item["company"],
        "company_id": item["company_id"],
        "year": item["year"],
        "pdf_filename": item["pdf"],
        "pdf_sha256": h,
        "page_count": total_pages,
        "file_size_bytes": pdf_path.stat().st_size,
        "bs_page_idx": bs_page_idx,
        "bs_page_1based": bs_page_idx + 1 if bs_page_idx is not None else None,
        "unit": unit,
        "printed_page": printed_page,
    })

(Path(r"C:\dev\AXA_research\output\_agent_runs") / "sample_inspection_summary.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
)
