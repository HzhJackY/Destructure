from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import yaml
import fitz
import jsonschema
import sys

REPO_ROOT = Path(r"C:\dev\AXA_research")
DOCU = REPO_ROOT / "docu"
CORPUS_ROOT = REPO_ROOT / "golden_corpus" / "v1.1.0" / "companies"
EVIDENCE_ROOT = REPO_ROOT / "golden_corpus" / "v1.1.0" / "evidence" / "crops"
RELEASE = REPO_ROOT / "releases" / "v6.13"

sys.path.insert(0, str(RELEASE))
from golden_identity import validate_identity_sidecar

SCHEMA_PORTFOLIO = json.loads((REPO_ROOT / "golden_corpus" / "v1.1.0" / "schema" / "investment_portfolio_golden.schema.json").read_text(encoding="utf-8"))

def render_evidence_crop(pdf_path: Path, page_no: int, out_path: Path, dpi: int = 300) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi)
    pix.save(str(out_path))

print("Helper ready.")
