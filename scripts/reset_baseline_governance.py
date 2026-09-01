import csv
from pathlib import Path

root = Path(r"C:\dev\AXA_research\golden_corpus\v1.1.0")

# 1. 12 Baseline filings for filing_inventory.csv
baseline_12 = [
    {"company": "中国平安", "report_year": "2023", "filename": "中国平安2023年报.pdf", "pdf_sha256": "f55538814200d77a61492ba216e45508f487064207bca6a4d90c7b55add43823", "page_count": "334", "file_size": "7225491", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国平安", "report_year": "2024", "filename": "中国平安2024年报.pdf", "pdf_sha256": "6ffff1cade59c64c8178494c083cac8a4011ef5ae2fed32f85dd488a64a809b2", "page_count": "346", "file_size": "11542073", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国平安", "report_year": "2025", "filename": "中国平安2025年报.pdf", "pdf_sha256": "860c455bbad9be59d3d1bf64bf683733feb79157212532df44b91d49a0b03c2a", "page_count": "370", "file_size": "9497402", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "新华保险", "report_year": "2023", "filename": "新华保险2023年报.pdf", "pdf_sha256": "046dbb6f39ab859f8c6c7beabf06010abf775a860964b24ab076f8053b1365b0", "page_count": "284", "file_size": "4651395", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "新华保险", "report_year": "2024", "filename": "新华保险2024年报.pdf", "pdf_sha256": "a983bd987c15ab982d9fbbce29255afff4bc90ca6ba5f15334d0784a8de1c7f0", "page_count": "292", "file_size": "4245883", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "新华保险", "report_year": "2025", "filename": "新华保险2025年报.pdf", "pdf_sha256": "4a5d6ee54dc0a351acac6d9d3ce1d0eee6d4a388c4c36c1668a35d5ffd35c528", "page_count": "295", "file_size": "6694301", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国太保", "report_year": "2023", "filename": "中国太保2023年报.pdf", "pdf_sha256": "716a65f266f6ed6dc12f6906db26b84aeac4745c212c8cb8687c7a4fa0fc9dab", "page_count": "287", "file_size": "8324038", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国太保", "report_year": "2024", "filename": "中国太保2024年报.pdf", "pdf_sha256": "3b6117c82942349be225d531b342cbbaf36255d02a2556525e697164a42e6b66", "page_count": "302", "file_size": "13373232", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国太保", "report_year": "2025", "filename": "中国太保2025年报.pdf", "pdf_sha256": "3787b6a6ec1bf480be2092e7bae156bd0f1d1b7f9f28bd9226d038951c788dee", "page_count": "310", "file_size": "13107566", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国人寿", "report_year": "2023", "filename": "中国人寿2023年年度报告.pdf", "pdf_sha256": "5ea1048c3a9323b37b1ad2e870da0fb54d9cfacdfba159aad4b9bec070edc18a", "page_count": "244", "file_size": "5800764", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国人寿", "report_year": "2024", "filename": "中国人寿2024年年度报告.pdf", "pdf_sha256": "3cc6db9bbd9c3c754548b6be288bcebae7187e5264eba59025237f5aa8c667e0", "page_count": "256", "file_size": "13075666", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
    {"company": "中国人寿", "report_year": "2025", "filename": "中国人寿2025年年度报告.pdf", "pdf_sha256": "575a833fd7b83ad3568483273645236eddb751a92ab89f7e1c09105d92cedb27", "page_count": "228", "file_size": "5031381", "document_modality": "TEXT_DOMINANT_OR_HYBRID", "canonical_for_testing": "True", "duplicate_group": "UNIQUE", "annotation_status": "CERTIFIED_GOLDEN"},
]

fieldnames = list(baseline_12[0].keys())
with (root / "filing_inventory.csv").open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(baseline_12)

# Reset golden_coverage_registry.csv to 12 rows with correct counts
cov_path = root / "golden_coverage_registry.csv"
with cov_path.open(encoding="utf-8") as f:
    cov_rows = [r for r in csv.DictReader(f) if r["filing_id"] in {f"{c['company'][:2]}_{c['report_year']}" for c in baseline_12} or r["company_id"] in {"PING_AN", "NEW_CHINA_LIFE", "CPIC", "CHINA_LIFE"}]

for r in cov_rows:
    if r["company_id"] == "CPIC":
        r["evidence_crops_status"] = "AVAILABLE"
        r["current_period_value_assertion_count"] = "0"
        r["comparative_period_value_assertion_count"] = "0"

with cov_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(cov_rows[0].keys()))
    writer.writeheader()
    writer.writerows(cov_rows)

print("BASELINE 12 RECONCILED")
