from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
import time
import urllib.request
import fitz

DOCU_DIR = Path(r"C:\dev\AXA_research\docu")
DOCU_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    # 中国人保 (601319.SH)
    {
        "company": "中国人保",
        "code": "601319.SH",
        "year": 2023,
        "type": "ANNUAL_REPORT",
        "filename": "中国人保2023年年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2024-03-27/1219411146.PDF"
    },
    {
        "company": "中国人保",
        "code": "601319.SH",
        "year": 2024,
        "type": "ANNUAL_REPORT",
        "filename": "中国人保2024年年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2025-03-28/1222927515.PDF"
    },
    {
        "company": "中国人保",
        "code": "601319.SH",
        "year": 2025,
        "type": "ANNUAL_REPORT",
        "filename": "中国人保2025年年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2026-03-27/1225037867.PDF"
    },

    # 中国再保 (01508.HK)
    {
        "company": "中国再保",
        "code": "01508.HK",
        "year": 2023,
        "type": "ANNUAL_REPORT",
        "filename": "中国再保2023年年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2024-04-26/1219882614.PDF"
    },
    {
        "company": "中国再保",
        "code": "01508.HK",
        "year": 2024,
        "type": "ANNUAL_REPORT",
        "filename": "中国再保2024年年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2025-04-29/1223406880.PDF"
    },
    {
        "company": "中国再保",
        "code": "01508.HK",
        "year": 2025,
        "type": "ANNUAL_REPORT",
        "filename": "中国再保2025年年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2026-04-29/1225263119.PDF"
    },

    # 众安在线 (06060.HK)
    {
        "company": "众安在线",
        "code": "06060.HK",
        "year": 2023,
        "type": "ANNUAL_REPORT",
        "filename": "众安在线2023年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2024-04-24/1219803357.PDF"
    },
    {
        "company": "众安在线",
        "code": "06060.HK",
        "year": 2024,
        "type": "ANNUAL_REPORT",
        "filename": "众安在线2024年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2025-04-24/1223276789.PDF"
    },
    {
        "company": "众安在线",
        "code": "06060.HK",
        "year": 2025,
        "type": "ANNUAL_REPORT",
        "filename": "众安在线2025年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2026-04-28/1225252098.PDF"
    },

    # 阳光保险 (06963.HK)
    {
        "company": "阳光保险",
        "code": "06963.HK",
        "year": 2023,
        "type": "ANNUAL_REPORT",
        "filename": "阳光保险2023年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2024-04-25/1219828027.PDF"
    },
    {
        "company": "阳光保险",
        "code": "06963.HK",
        "year": 2024,
        "type": "ANNUAL_REPORT",
        "filename": "阳光保险2024年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2025-04-25/1223308791.PDF"
    },
    {
        "company": "阳光保险",
        "code": "06963.HK",
        "year": 2025,
        "type": "ANNUAL_REPORT",
        "filename": "阳光保险2025年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2026-04-27/1225213013.PDF"
    },

    # 友邦保险 (01299.HK)
    {
        "company": "友邦保险",
        "code": "01299.HK",
        "year": 2023,
        "type": "ANNUAL_REPORT",
        "filename": "友邦保险2023年报.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2024-04-12/1219593737.PDF"
    },
    {
        "company": "友邦保险",
        "code": "01299.HK",
        "year": 2024,
        "type": "ANNUAL_REPORT",
        "filename": "友邦保险2024年报.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2025-04-08/1223029772.PDF"
    },
    {
        "company": "友邦保险",
        "code": "01299.HK",
        "year": 2025,
        "type": "ANNUAL_REPORT",
        "filename": "友邦保险2025年报.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2026-04-15/1225106734.PDF"
    },

    # 中国财险 (02328.HK)
    {
        "company": "中国财险",
        "code": "02328.HK",
        "year": 2023,
        "type": "ANNUAL_REPORT",
        "filename": "中国财险2023年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2024-04-08/1219535957.PDF"
    },
    {
        "company": "中国财险",
        "code": "02328.HK",
        "year": 2024,
        "type": "ANNUAL_REPORT",
        "filename": "中国财险2024年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2025-04-02/1222989921.PDF"
    },
    {
        "company": "中国财险",
        "code": "02328.HK",
        "year": 2025,
        "type": "ANNUAL_REPORT",
        "filename": "中国财险2025年度报告.pdf",
        "url": "http://static.cninfo.com.cn/finalpage/2026-04-01/1225070895.PDF"
    },
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

results = []
print(f"Starting download of {len(TARGETS)} reference sample filings...")

for item in TARGETS:
    dest = DOCU_DIR / item["filename"]
    print(f"\nDownloading: {item['company']} {item['year']} -> {item['filename']} ...")
    if dest.exists() and dest.stat().st_size > 100000:
        print(f"  Existing file found ({dest.stat().st_size} bytes). Verifying integrity...")
    else:
        req = urllib.request.Request(item["url"], headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp, dest.open("wb") as f:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            print(f"  Downloaded: {dest.stat().st_size} bytes")
        except Exception as e:
            print(f"  Download error for {item['filename']}: {e}")
            continue

    # Integrity verification via PyMuPDF
    try:
        doc = fitz.open(dest)
        page_count = len(doc)
        # Check text layer
        sample_text = "".join(doc[min(i, page_count - 1)].get_text() for i in range(min(5, page_count)))
        modality = "NATIVE_DIGITAL" if len(sample_text.strip()) > 200 else "IMAGE_DOMINANT_OR_LOW_TEXT"
        
        # Calculate sha256
        h = sha256()
        with dest.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
        
        results.append({
            "company": item["company"],
            "stock_code": item["code"],
            "report_year": item["year"],
            "report_type": item["type"],
            "filename": item["filename"],
            "pdf_sha256": digest,
            "page_count": page_count,
            "file_size_bytes": dest.stat().st_size,
            "modality": modality,
            "verification_status": "PASS",
        })
        print(f"  Verified PASS: pages={page_count}, modality={modality}, sha={digest[:16]}...")
    except Exception as e:
        print(f"  Verification failed: {e}")

manifest_path = DOCU_DIR / "sample_manifest.csv"
fieldnames = [
    "company", "stock_code", "report_year", "report_type",
    "filename", "pdf_sha256", "page_count", "file_size_bytes",
    "modality", "verification_status",
]

# Include existing 12 baseline files in manifest as well
for baseline in DOCU_DIR.glob("*.pdf"):
    if not any(r["filename"] == baseline.name for r in results):
        try:
            doc = fitz.open(baseline)
            pc = len(doc)
            st = "".join(doc[min(i, pc - 1)].get_text() for i in range(min(5, pc)))
            mod = "NATIVE_DIGITAL" if len(st.strip()) > 200 else "IMAGE_DOMINANT_OR_LOW_TEXT"
            h = sha256(baseline.read_bytes()).hexdigest()
            results.append({
                "company": "BASELINE",
                "stock_code": "BASELINE",
                "report_year": "2023-2025",
                "report_type": "ANNUAL_REPORT",
                "filename": baseline.name,
                "pdf_sha256": h,
                "page_count": pc,
                "file_size_bytes": baseline.stat().st_size,
                "modality": mod,
                "verification_status": "PASS",
            })
        except Exception:
            pass

with manifest_path.open("w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(results)

print(f"\nAll operations completed! Manifest written to {manifest_path}. Total valid samples: {len(results)}")
