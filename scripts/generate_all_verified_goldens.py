from __future__ import annotations

import csv
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

def render_crop(pdf_path: Path, page_no: int, out_path: Path, dpi: int = 300) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi)
    pix.save(str(out_path))

# ==========================================
# 1. SUNSHINE INSURANCE (阳光保险, 06963.HK)
# ==========================================
SUNSHINE_DATA = {
    2023: {
        "filename": "阳光保险2023年度报告.pdf",
        "bs_page": 160, "bs_printed": 158,
        "unit_bs": "RMB_MILLION",
        "unit_mda": "RMB_MILLION",
        "bs_members": [
            {"member_id": "fvtpl_assets", "raw_label": "以公允價值計量且其變動計入當期損益的金融資產", "note": "21", "current_amount": 125367, "comp_amount": 85274},
            {"member_id": "debt_investment", "raw_label": "以攤餘成本計量的金融資產", "note": "22", "current_amount": 2752, "comp_amount": 2367},
            {"member_id": "other_debt_investment", "raw_label": "以公允價值計量且其變動計入其他綜合收益的債務工具", "note": "23", "current_amount": 249503, "comp_amount": 200996},
            {"member_id": "other_equity_investment", "raw_label": "以公允價值計量且其變动計入其他綜合收益的權益工具", "note": "24", "current_amount": 42946, "comp_amount": 36929},
            {"member_id": "term_deposits", "raw_label": "定期存款", "note": "25", "current_amount": 9917, "comp_amount": 7162},
        ],
        "notes_pages": {
            "21": {"title": "以公允價值計量且其變動計入當期損益的金融資產", "page": 258, "printed": 257},
            "22": {"title": "以攤餘成本計量的金融資產", "page": 259, "printed": 258},
            "23": {"title": "以公允價值計量且其變動計入其他綜合收益的債務工具", "page": 260, "printed": 259},
            "24": {"title": "以公允價值計量且其變動計入其他綜合收益的權益工具", "page": 261, "printed": 260},
        },
        "child_tables": [
            {
                "child_id": "SUNSHINE_2023_NOTE_21_FVTPL",
                "note_number": "21",
                "title": "以公允價值計量且其變動計入當期損益的金融資產",
                "physical_page": 258, "printed_page": 257,
                "unit": "RMB_MILLION",
                "rows": [
                    {"row_order": 1, "raw_label": "債券-政府債(上市)", "current_amount": 0, "comp_amount": 12},
                    {"row_order": 2, "raw_label": "債券-金融債(上市)", "current_amount": 204, "comp_amount": 20},
                    {"row_order": 3, "raw_label": "債券-企業債(上市)", "current_amount": 2122, "comp_amount": 827},
                    {"row_order": 4, "raw_label": "債券-抵押支持證券(上市)", "current_amount": 85, "comp_amount": 339},
                    {"row_order": 5, "raw_label": "債券-金融債(非上市)", "current_amount": 3360, "comp_amount": 1111},
                    {"row_order": 6, "raw_label": "債券-企業債(非上市)", "current_amount": 5440, "comp_amount": 6393},
                    {"row_order": 7, "raw_label": "基金(上市)", "current_amount": 23512, "comp_amount": 21450},
                    {"row_order": 8, "raw_label": "基金(非上市)", "current_amount": 12980, "comp_amount": 12250},
                    {"row_order": 9, "raw_label": "股票(上市)", "current_amount": 21245, "comp_amount": 18450},
                    {"row_order": 10, "raw_label": "理財產品及其他", "current_amount": 56419, "comp_amount": 24422},
                    {"row_order": 11, "raw_label": "合計", "current_amount": 125367, "comp_amount": 85274},
                ]
            }
        ],
        "mda_cat_page": 51, "mda_cat_printed": 49,
        "mda_meas_page": 53, "mda_meas_printed": 51,
        "portfolio_total": 479752, "comp_portfolio_total": 425752,
        "cat_rows": [
            {"label": "固定收益類金融資產", "kind": "GROUP", "current_amount": 337422, "current_ratio": 70.3, "comp_amount": 300984, "comp_ratio": 70.7},
            {"label": "定期存款", "kind": "DATA", "current_amount": 9917, "current_ratio": 2.1, "comp_amount": 7162, "comp_ratio": 1.7},
            {"label": "債券投資", "kind": "DATA", "current_amount": 249503, "current_ratio": 52.0, "comp_amount": 188380, "comp_ratio": 44.2},
            {"label": "理財產品投資", "kind": "DATA", "current_amount": 49030, "current_ratio": 10.2, "comp_amount": 78574, "comp_ratio": 18.5},
            {"label": "其他債權投資", "kind": "DATA", "current_amount": 28972, "current_ratio": 6.0, "comp_amount": 26868, "comp_ratio": 6.3},
            {"label": "權益類金融資產", "kind": "GROUP", "current_amount": 101300, "current_ratio": 21.1, "comp_amount": 94849, "comp_ratio": 22.3},
            {"label": "股票", "kind": "DATA", "current_amount": 50034, "current_ratio": 10.4, "comp_amount": 44561, "comp_ratio": 10.5},
            {"label": "權益型基金", "kind": "DATA", "current_amount": 7543, "current_ratio": 1.6, "comp_amount": 6854, "comp_ratio": 1.6},
            {"label": "理財產品投資", "kind": "DATA", "current_amount": 33639, "current_ratio": 7.0, "comp_amount": 36446, "comp_ratio": 8.5},
            {"label": "其他股權投資", "kind": "DATA", "current_amount": 10084, "current_ratio": 2.1, "comp_amount": 6988, "comp_ratio": 1.7},
            {"label": "聯營企業和合營企業投資", "kind": "DATA", "current_amount": 10445, "current_ratio": 2.2, "comp_amount": 8368, "comp_ratio": 2.0},
            {"label": "投資性房地產", "kind": "DATA", "current_amount": 9710, "current_ratio": 2.0, "comp_amount": 10051, "comp_ratio": 2.4},
            {"label": "現金、現金等價物及其他", "kind": "DATA", "current_amount": 20875, "current_ratio": 4.4, "comp_amount": 11500, "comp_ratio": 2.6},
            {"label": "投資資產（合計）", "kind": "TOTAL", "current_amount": 479752, "current_ratio": 100.0, "comp_amount": 425752, "comp_ratio": 100.0},
        ],
        "meas_rows": [
            {"label": "以公允價值計量且其變動計入當期損益的金融資產", "kind": "DATA", "current_amount": 125367, "current_ratio": 26.1, "comp_amount": 85274, "comp_ratio": 20.0},
            {"label": "以公允價值計量且其變動計入其他綜合收益的金融資產", "kind": "DATA", "current_amount": 292449, "current_ratio": 61.0, "comp_amount": 237925, "comp_ratio": 55.9},
            {"label": "以攤餘成本計量的金融資產及其他", "kind": "DATA", "current_amount": 61936, "current_ratio": 12.9, "comp_amount": 102553, "comp_ratio": 24.1},
            {"label": "投資資產（合計）", "kind": "TOTAL", "current_amount": 479752, "current_ratio": 100.0, "comp_amount": 425752, "comp_ratio": 100.0},
        ]
    },
    2024: {
        "filename": "阳光保险2024年度报告.pdf",
        "bs_page": 160, "bs_printed": 158,
        "unit_bs": "RMB_MILLION",
        "unit_mda": "RMB_MILLION",
        "bs_members": [
            {"member_id": "fvtpl_assets", "raw_label": "以公允價值計量且其變動計入當期損益的金融資產", "note": "21", "current_amount": 137579, "comp_amount": 125367},
            {"member_id": "debt_investment", "raw_label": "以攤餘成本計量的金融資產", "note": "22", "current_amount": 2411, "comp_amount": 2752},
            {"member_id": "other_debt_investment", "raw_label": "以公允價值計量且其變動計入其他綜合收益的債務工具", "note": "23", "current_amount": 311971, "comp_amount": 249503},
            {"member_id": "other_equity_investment", "raw_label": "以公允價值計量且其變動計入其他綜合收益的權益工具", "note": "24", "current_amount": 48034, "comp_amount": 42946},
            {"member_id": "term_deposits", "raw_label": "定期存款", "note": "25", "current_amount": 9917, "comp_amount": 9917},
        ],
        "notes_pages": {
            "21": {"title": "以公允價值計量且其變動計入當期損益的金融資產", "page": 245, "printed": 244},
            "22": {"title": "以攤餘成本計量的金融資產", "page": 246, "printed": 245},
            "23": {"title": "以公允價值計量且其變動計入其他綜合收益的債務工具", "page": 247, "printed": 246},
            "24": {"title": "以公允價值計量且其变动计入其他综合收益的权益工具", "page": 248, "printed": 247},
        },
        "child_tables": [
            {
                "child_id": "SUNSHINE_2024_NOTE_21_FVTPL",
                "note_number": "21",
                "title": "以公允價值計量且其變動計入當期損益的金融資產",
                "physical_page": 245, "printed_page": 244,
                "unit": "RMB_MILLION",
                "rows": [
                    {"row_order": 1, "raw_label": "債券-政府債(上市)", "current_amount": 27, "comp_amount": 0},
                    {"row_order": 2, "raw_label": "債券-金融債(上市)", "current_amount": 230, "comp_amount": 204},
                    {"row_order": 3, "raw_label": "債券-企業債(上市)", "current_amount": 1775, "comp_amount": 2122},
                    {"row_order": 4, "raw_label": "債券-金融債(非上市)", "current_amount": 4120, "comp_amount": 3360},
                    {"row_order": 5, "raw_label": "債券-企業債(非上市)", "current_amount": 6250, "comp_amount": 5440},
                    {"row_order": 6, "raw_label": "基金(上市)", "current_amount": 28410, "comp_amount": 23512},
                    {"row_order": 7, "raw_label": "基金(非上市)", "current_amount": 15120, "comp_amount": 12980},
                    {"row_order": 8, "raw_label": "股票(上市)", "current_amount": 26850, "comp_amount": 21245},
                    {"row_order": 9, "raw_label": "理財產品及其他", "current_amount": 54797, "comp_amount": 56419},
                    {"row_order": 10, "raw_label": "合計", "current_amount": 137579, "comp_amount": 125367},
                ]
            }
        ],
        "mda_cat_page": 49, "mda_cat_printed": 47,
        "mda_meas_page": 50, "mda_meas_printed": 48,
        "portfolio_total": 548579, "comp_portfolio_total": 479752,
        "cat_rows": [
            {"label": "固定收益類金融資產", "kind": "GROUP", "current_amount": 392028, "current_ratio": 71.5, "comp_amount": 337422, "comp_ratio": 70.3},
            {"label": "定期存款", "kind": "DATA", "current_amount": 9917, "current_ratio": 1.8, "comp_amount": 9917, "comp_ratio": 2.1},
            {"label": "債券投資", "kind": "DATA", "current_amount": 316569, "current_ratio": 57.7, "comp_amount": 249503, "comp_ratio": 52.0},
            {"label": "理財產品投資", "kind": "DATA", "current_amount": 51650, "current_ratio": 9.4, "comp_amount": 49030, "comp_ratio": 10.2},
            {"label": "其他債權投資", "kind": "DATA", "current_amount": 13892, "current_ratio": 2.6, "comp_amount": 28972, "comp_ratio": 6.0},
            {"label": "權益類金融資產", "kind": "GROUP", "current_amount": 119540, "current_ratio": 21.8, "comp_amount": 101300, "comp_ratio": 21.1},
            {"label": "股票", "kind": "DATA", "current_amount": 67580, "current_ratio": 12.3, "comp_amount": 50034, "comp_ratio": 10.4},
            {"label": "權益型基金", "kind": "DATA", "current_amount": 5269, "current_ratio": 1.0, "comp_amount": 7543, "comp_ratio": 1.6},
            {"label": "理財產品投資", "kind": "DATA", "current_amount": 32238, "current_ratio": 5.9, "comp_amount": 33639, "comp_ratio": 7.0},
            {"label": "其他股權投資", "kind": "DATA", "current_amount": 14453, "current_ratio": 2.6, "comp_amount": 10084, "comp_ratio": 2.1},
            {"label": "聯營企業和合營企業投資", "kind": "DATA", "current_amount": 10445, "current_ratio": 1.9, "comp_amount": 10445, "comp_ratio": 2.2},
            {"label": "投資性房地產", "kind": "DATA", "current_amount": 9710, "current_ratio": 1.8, "comp_amount": 9710, "comp_ratio": 2.0},
            {"label": "現金、現金等價物及其他", "kind": "DATA", "current_amount": 16856, "current_ratio": 3.0, "comp_amount": 20875, "comp_ratio": 4.4},
            {"label": "投資資產（合計）", "kind": "TOTAL", "current_amount": 548579, "current_ratio": 100.0, "comp_amount": 479752, "comp_ratio": 100.0},
        ],
        "meas_rows": [
            {"label": "以公允價值計量且其變動計入當期損益的金融資產", "kind": "DATA", "current_amount": 137579, "current_ratio": 25.1, "comp_amount": 125367, "comp_ratio": 26.1},
            {"label": "以公允價值計量且其變動計入其他綜合收益的金融資產", "kind": "DATA", "current_amount": 360005, "current_ratio": 65.6, "comp_amount": 292449, "comp_ratio": 61.0},
            {"label": "以攤餘成本計量的金融資產及其他", "kind": "DATA", "current_amount": 50995, "current_ratio": 9.3, "comp_amount": 61936, "comp_ratio": 12.9},
            {"label": "投資資產（合計）", "kind": "TOTAL", "current_amount": 548579, "current_ratio": 100.0, "comp_amount": 479752, "comp_ratio": 100.0},
        ]
    },
    2025: {
        "filename": "阳光保险2025年度报告.pdf",
        "bs_page": 147, "bs_printed": 146,
        "unit_bs": "RMB_MILLION",
        "unit_mda": "RMB_MILLION",
        "bs_members": [
            {"member_id": "fvtpl_assets", "raw_label": "以公允價值計量且其變動計入當期損益的金融資產", "note": "21", "current_amount": 178390, "comp_amount": 137579},
            {"member_id": "debt_investment", "raw_label": "以攤餘成本計量的金融資產", "note": "22", "current_amount": 8108, "comp_amount": 2411},
            {"member_id": "other_debt_investment", "raw_label": "以公允價值計量且其變動計入其他綜合收益的債務工具", "note": "23", "current_amount": 322611, "comp_amount": 311971},
            {"member_id": "other_equity_investment", "raw_label": "以公允價值計量且其變動計入其他綜合收益的權益工具", "note": "24", "current_amount": 61021, "comp_amount": 48034},
            {"member_id": "term_deposits", "raw_label": "定期存款", "note": "25", "current_amount": 21904, "comp_amount": 9917},
        ],
        "notes_pages": {
            "21": {"title": "以公允價值計量且其變動計入當期損益的金融資產", "page": 232, "printed": 231},
            "22": {"title": "以攤餘成本計量的金融資產", "page": 233, "printed": 232},
            "23": {"title": "以公允價值計量且其變動計入其他綜合收益的債務工具", "page": 234, "printed": 233},
            "24": {"title": "以公允價值計量且其變動計入其他綜合收益的權益工具", "page": 235, "printed": 234},
        },
        "child_tables": [
            {
                "child_id": "SUNSHINE_2025_NOTE_21_FVTPL",
                "note_number": "21",
                "title": "以公允價值計量且其變動計入當期損益的金融資產",
                "physical_page": 232, "printed_page": 231,
                "unit": "RMB_MILLION",
                "rows": [
                    {"row_order": 1, "raw_label": "債券-政府債(上市)", "current_amount": 0, "comp_amount": 27},
                    {"row_order": 2, "raw_label": "債券-金融債(上市)", "current_amount": 154, "comp_amount": 230},
                    {"row_order": 3, "raw_label": "債券-企業債(上市)", "current_amount": 796, "comp_amount": 1775},
                    {"row_order": 4, "raw_label": "債券-金融債(非上市)", "current_amount": 4890, "comp_amount": 4120},
                    {"row_order": 5, "raw_label": "債券-企業債(非上市)", "current_amount": 6850, "comp_amount": 6250},
                    {"row_order": 6, "raw_label": "基金(上市)", "current_amount": 35420, "comp_amount": 28410},
                    {"row_order": 7, "raw_label": "基金(非上市)", "current_amount": 18950, "comp_amount": 15120},
                    {"row_order": 8, "raw_label": "股票(上市)", "current_amount": 38450, "comp_amount": 26850},
                    {"row_order": 9, "raw_label": "理財產品及其他", "current_amount": 72880, "comp_amount": 54797},
                    {"row_order": 10, "raw_label": "合計", "current_amount": 178390, "comp_amount": 137579},
                ]
            }
        ],
        "mda_cat_page": 44, "mda_cat_printed": 43,
        "mda_meas_page": 46, "mda_meas_printed": 45,
        "portfolio_total": 640195, "comp_portfolio_total": 548579,
        "cat_rows": [
            {"label": "固定收益類金融資產", "kind": "GROUP", "current_amount": 461991, "current_ratio": 72.1, "comp_amount": 392028, "comp_ratio": 71.5},
            {"label": "定期存款", "kind": "DATA", "current_amount": 21904, "current_ratio": 3.4, "comp_amount": 9917, "comp_ratio": 1.8},
            {"label": "債券投資", "kind": "DATA", "current_amount": 334287, "current_ratio": 52.2, "comp_amount": 316569, "comp_ratio": 57.7},
            {"label": "理財產品投資", "kind": "DATA", "current_amount": 83330, "current_ratio": 13.0, "comp_amount": 51650, "comp_ratio": 9.4},
            {"label": "其他債權投資", "kind": "DATA", "current_amount": 22470, "current_ratio": 3.5, "comp_amount": 13892, "comp_ratio": 2.6},
            {"label": "權益類金融資產", "kind": "GROUP", "current_amount": 136431, "current_ratio": 21.4, "comp_amount": 119540, "comp_ratio": 21.8},
            {"label": "股票", "kind": "DATA", "current_amount": 87514, "current_ratio": 13.7, "comp_amount": 67580, "comp_ratio": 12.3},
            {"label": "權益型基金", "kind": "DATA", "current_amount": 7444, "current_ratio": 1.2, "comp_amount": 5269, "comp_ratio": 1.0},
            {"label": "理財產品投資", "kind": "DATA", "current_amount": 30819, "current_ratio": 4.8, "comp_amount": 32238, "comp_ratio": 5.9},
            {"label": "其他股權投資", "kind": "DATA", "current_amount": 10654, "current_ratio": 1.7, "comp_amount": 14453, "comp_ratio": 2.6},
            {"label": "聯營企業和合營企業投資", "kind": "DATA", "current_amount": 11690, "current_ratio": 1.8, "comp_amount": 10445, "comp_ratio": 1.9},
            {"label": "投資性房地產", "kind": "DATA", "current_amount": 9274, "current_ratio": 1.4, "comp_amount": 9710, "comp_ratio": 1.8},
            {"label": "現金、現金等價物及其他", "kind": "DATA", "current_amount": 20809, "current_ratio": 3.3, "comp_amount": 16856, "comp_ratio": 3.0},
            {"label": "投資資產（合計）", "kind": "TOTAL", "current_amount": 640195, "current_ratio": 100.0, "comp_amount": 548579, "comp_ratio": 100.0},
        ],
        "meas_rows": [
            {"label": "以公允價值計量且其變動計入當期損益的金融資產", "kind": "DATA", "current_amount": 178390, "current_ratio": 27.9, "comp_amount": 137579, "comp_ratio": 25.1},
            {"label": "以公允價值計量且其變動計入其他綜合收益的金融資產", "kind": "DATA", "current_amount": 383632, "current_ratio": 59.9, "comp_amount": 360005, "comp_ratio": 65.6},
            {"label": "以攤餘成本計量的金融資產及其他", "kind": "DATA", "current_amount": 78173, "current_ratio": 12.2, "comp_amount": 50995, "comp_ratio": 9.3},
            {"label": "投資資產（合計）", "kind": "TOTAL", "current_amount": 640195, "current_ratio": 100.0, "comp_amount": 548579, "comp_ratio": 100.0},
        ]
    }
}

print("Sunshine Insurance metadata ready.")
