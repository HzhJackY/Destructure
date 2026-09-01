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

print("Starting Golden Data Generation & Visual Crop Rendering for 5 companies (15 filings)...")
