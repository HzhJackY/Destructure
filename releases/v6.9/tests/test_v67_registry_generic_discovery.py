"""Targeted v6.7 registry/generic-discovery acceptance (not full regression)."""
from __future__ import annotations
import tempfile
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from data_home import ensure_data_home
from backend_context import build_backend_services
from accounting_semantic_parser_v2 import build_semantic_rows, arithmetic_relationships

PINGAN=Path(r"C:\dev\AXA_research\docu\中国平安2023年报.pdf")
AXA=Path(r"C:\dev\AXA_research\docu\工银安盛2023年报.pdf")

def main():
    # 中国平安是本 release 的受控真实样本；工银安盛不是 v6.7
    # 安装包的必备 fixture，缺失时不应让发布验收误报为产品失败。
    assert PINGAN.exists(), PINGAN
    with tempfile.TemporaryDirectory(prefix="v67_registry_") as tmp:
        backend=build_backend_services(ensure_data_home(Path(tmp),ROOT/"metric_aliases.json"))
        registry=backend.research_definition_service
        families={x["family_id"]:x for x in registry.families()}
        assert {"financial_investment","investment_portfolio"}.issubset(families)
        assert [x["member_id"] for x in registry.members("investment_portfolio")]==["portfolio_by_category","portfolio_by_measurement"]
        definition=registry.definition("INVESTMENT_PORTFOLIO_V1")
        assert definition and definition["payload"]["table_families"]==["investment_portfolio"]
        clone=registry.clone_definition("INVESTMENT_PORTFOLIO_V1","INVESTMENT_PORTFOLIO_V1_TEST")
        assert clone["definition_version"]=="INVESTMENT_PORTFOLIO_V1_TEST"
        result=backend.generic_discovery_service.discover(pdf_path=PINGAN,definition_id="INVESTMENT_PORTFOLIO_V1",company="中国平安",report_year="2023")
        candidates=result["candidates"]
        assert len(candidates)==2
        assert all(x["table_family"]=="investment_portfolio" for x in candidates)
        assert all(x["locator_method"]=="DIRECT_NOTE_TITLE_ROW_COLUMN_SIGNATURE" for x in candidates)
        assert {x["member_table"] for x in candidates}=={"portfolio_by_category","portfolio_by_measurement"}
        assert all(x["candidate_note_pdf_page_index"] for x in candidates)
        assert len(result["occurrences"]) == 2
        assert all(x["child_rows"][0]["note_target_candidates"] for x in result["occurrences"])
        # A second company exercises generic abstention without manufacturing a table.
        if AXA.exists():
            other=backend.generic_discovery_service.discover(pdf_path=AXA,definition_id="INVESTMENT_PORTFOLIO_V1",company="工银安盛",report_year="2023")
            assert all(x["status"] in {"NEEDS_REVIEW","REVIEW_REQUIRED","UNRESOLVED"} for x in other["candidates"])
        rows=build_semantic_rows([
            {"raw_item":"股权型金融资产","row_level":0,"value":None,"row_type":"SECTION"},
            {"raw_item":"股票","row_level":1,"value":100,"unit":"百万元"},
            {"raw_item":None,"row_level":0,"value":100,"unit":"百万元"},
        ])
        assert rows[-1]["row_role"]=="IMPLICIT_TOTAL" and rows[-1]["raw_item"] is None
        assert rows[-1]["label_derivation"]=="DERIVED_FROM_STRUCTURE"
        assert arithmetic_relationships(rows)[0]["status"]=="CANDIDATE_ONLY"
    print("RESEARCH_DEFINITION_REGISTRY_PASS")
    print("PATTERN_D_DIRECT_TABLE_FAMILY_PASS")
    print("ACCOUNTING_SEMANTIC_ROW_ROLE_PASS")

if __name__=="__main__": main()
