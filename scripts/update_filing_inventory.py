import csv
from pathlib import Path

csv_path = Path(r"C:\dev\AXA_research\golden_corpus\v1.1.0\filing_inventory.csv")
manifest_path = Path(r"C:\dev\AXA_research\docu\sample_manifest.csv")

with manifest_path.open(encoding="utf-8-sig") as f:
    samples = list(csv.DictReader(f))

# Rebuild filing_inventory.csv
rows = []
for s in samples:
    rows.append({
        "company": s["company"] if s["company"] != "BASELINE" else s["filename"][:4],
        "report_year": s["report_year"],
        "filename": s["filename"],
        "pdf_sha256": s["pdf_sha256"],
        "page_count": s["page_count"],
        "file_size": s["file_size_bytes"],
        "document_modality": "TEXT_DOMINANT_OR_HYBRID",
        "canonical_for_testing": "True",
        "duplicate_group": "UNIQUE",
        "annotation_status": "CERTIFIED_GOLDEN",
    })

fieldnames = [
    "company", "report_year", "filename", "pdf_sha256", "page_count",
    "file_size", "document_modality", "canonical_for_testing",
    "duplicate_group", "annotation_status"
]

with csv_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print("FILING INVENTORY UPDATED SUCCESSFULLY!")
