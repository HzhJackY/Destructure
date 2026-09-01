"""Generate the 12 real disclosure pattern corpus files."""
import json, hashlib
from pathlib import Path

DOCU = Path(r"C:\dev\AXA_research\docu")
OUT = Path(__file__).resolve().parent

PATTERNS = [
    # Ping An — EXPLICIT_PARENT_STANDARD (text layer)
    ("PINGAN_2023", "中国平安", "2023", "中国平安2023年报.pdf",
     "TEXT_LAYER", "EXPLICIT_PARENT_STANDARD", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity"], []),
    ("PINGAN_2024", "中国平安", "2024", "中国平安2024年报.pdf",
     "TEXT_LAYER", "EXPLICIT_PARENT_STANDARD", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity"], []),
    ("PINGAN_2025", "中国平安", "2025", "中国平安2025年报.pdf",
     "TEXT_LAYER", "EXPLICIT_PARENT_STANDARD", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity"], []),

    # Xinhua — EXPLICIT_PARENT_MULTI_NOTE
    ("XINHUA_2023", "新华保险", "2023", "新华保险2023年报.pdf",
     "TEXT_LAYER", "EXPLICIT_PARENT_MULTI_NOTE", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity"], ["requires_cross_page_boundary"]),
    ("XINHUA_2024", "新华保险", "2024", "新华保险2024年报.pdf",
     "TEXT_LAYER", "EXPLICIT_PARENT_MULTI_NOTE", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity"], ["requires_cross_page_boundary"]),
    ("XINHUA_2025", "新华保险", "2025", "新华保险2025年报.pdf",
     "TEXT_LAYER", "EXPLICIT_PARENT_MULTI_NOTE", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity"], ["requires_cross_page_boundary"]),

    # CPIC — IMAGE_DOMINANT_EXPLICIT_PARENT
    ("CPIC_2023", "中国太保", "2023", "中国太保2023年报.pdf",
     "IMAGE_DOMINANT", "IMAGE_DOMINANT_EXPLICIT_PARENT", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity","available_for_sale_assets","held_to_maturity_investments"],
     ["requires_ocr","requires_image_layout","requires_transition_logic"]),
    ("CPIC_2024", "中国太保", "2024", "中国太保2024年报.pdf",
     "IMAGE_DOMINANT", "IMAGE_DOMINANT_EXPLICIT_PARENT", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity"],
     ["requires_ocr","requires_image_layout"]),
    ("CPIC_2025", "中国太保", "2025", "中国太保2025年报.pdf",
     "IMAGE_DOMINANT", "IMAGE_DOMINANT_EXPLICIT_PARENT", "EXPLICIT_PARENT", True, "金融投资",
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     ["time_deposits","long_term_equity"],
     ["requires_ocr","requires_image_layout"]),

    # China Life — IMAGE_BASED_IMPLICIT_MEMBER_SET_SCATTERED
    ("CHINA_LIFE_2023", "中国人寿", "2023", "中国人寿2023年年度报告.pdf",
     "IMAGE_BASED", "IMAGE_BASED_IMPLICIT_MEMBER_SET_SCATTERED", "IMPLICIT_MEMBER_SET", False, None,
     ["legacy_fvtpl_assets","available_for_sale_assets","held_to_maturity_investments","legacy_loans"],
     [], ["requires_ocr","requires_image_layout","requires_scattered_member_discovery","requires_parent_inference"]),
    ("CHINA_LIFE_2024", "中国人寿", "2024", "中国人寿2024年年度报告.pdf",
     "IMAGE_BASED", "IMAGE_BASED_IMPLICIT_MEMBER_SET_SCATTERED", "IMPLICIT_MEMBER_SET", False, None,
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     [], ["requires_ocr","requires_image_layout","requires_scattered_member_discovery","requires_parent_inference"]),
    ("CHINA_LIFE_2025", "中国人寿", "2025", "中国人寿2025年年度报告.pdf",
     "IMAGE_BASED", "IMAGE_BASED_IMPLICIT_MEMBER_SET_SCATTERED", "IMPLICIT_MEMBER_SET", False, None,
     ["fvtpl_assets","debt_investment","other_debt_investment","other_equity_investment"],
     [], ["requires_ocr","requires_image_layout","requires_scattered_member_discovery","requires_parent_inference"]),
]

for (fid, company, year, pdf_name, modality, pattern, mode, parent_present,
     parent_label, required, forbidden, constraints) in PATTERNS:
    p = DOCU / pdf_name
    sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "FILE_NOT_FOUND"
    data = {
        "fixture_id": fid, "company": company, "report_year": year,
        "pdf_filename": pdf_name, "pdf_sha256": sha,
        "document_modality": modality, "disclosure_pattern": pattern,
        "statement_scope": "CONSOLIDATED",
        "research_definition_id": "FINANCIAL_INVESTMENT_V1",
        "definition_version": "FINANCIAL_INVESTMENT_V1",
        "expected_resolution_mode": mode,
        "expected_parent_present": parent_present,
        "expected_parent_label": parent_label,
        "expected_required_members": required,
        "expected_forbidden_members": forbidden,
        "known_constraints": constraints,
        "source_pages": [],
        "annotation_status": "PATTERN_CANDIDATE",
    }
    name = f"{'pingan' if '平安' in company else 'xinhua' if '新华' in company else 'cpic' if '太保' in company else 'china_life'}_{year}.json"
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {name}: {sha[:16]}...")

print(f"\nCreated {len(PATTERNS)} pattern files in {OUT}")
