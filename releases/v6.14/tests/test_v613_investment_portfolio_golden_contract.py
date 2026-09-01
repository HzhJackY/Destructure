from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = REPO_ROOT / "golden_corpus" / "v1.1.0"
REGISTRY = CORPUS_ROOT / "investment_portfolio_golden_registry.csv"
SCHEMA = CORPUS_ROOT / "schema" / "investment_portfolio_golden.schema.json"


def _rows() -> list[dict[str, str]]:
    with REGISTRY.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_golden(row: dict[str, str]) -> dict:
    with (CORPUS_ROOT / row["golden_file"]).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_registry_has_twelve_physically_verified_listed_report_goldens() -> None:
    rows = _rows()
    assert len(rows) == 12
    assert all(row["annotation_status"] == "CERTIFIED_GOLDEN_ROW_VALUES" for row in rows)
    assert all(row["row_value_coverage"] == "FULL" for row in rows)


def test_all_portfolio_goldens_validate_and_are_native_text_only() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for row in _rows():
        golden = _load_golden(row)
        jsonschema.validate(golden, schema)
        assert golden["golden_id"] == row["golden_id"]
        for asset in golden["physical_assets"]:
            assert asset["native_text_verified"] is True
            assert asset["ocr_used"] is False


def test_all_logical_blocks_have_ordered_row_level_values() -> None:
    total_rows = 0
    for registry_row in _rows():
        golden = _load_golden(registry_row)
        for asset in golden["physical_assets"]:
            for block in asset["blocks"]:
                rows = block["rows"]
                assert rows
                assert [row["row_order"] for row in rows] == list(range(1, len(rows) + 1))
                assert all(row["normalized_label"] for row in rows)
                for row in rows:
                    if row["row_kind"] != "GROUP":
                        # Source may disclose N/A in one accounting regime,
                        # but must disclose at least one amount pair.
                        assert row["current_amount"] is not None or row["comparative_amount"] is not None
                total_rows += len(rows)
    assert total_rows == 281


def test_source_total_rows_match_certified_block_totals_when_present() -> None:
    checked = 0
    for registry_row in _rows():
        golden = _load_golden(registry_row)
        for asset in golden["physical_assets"]:
            for block in asset["blocks"]:
                for row in block["rows"]:
                    if row["row_kind"] == "TOTAL":
                        assert row["current_amount"] == block["current_period"]["amount"]
                        assert row["comparative_amount"] == block["comparative_period"]["amount"]
                        checked += 1
    assert checked == 23


def test_physical_asset_and_logical_block_counts_match_registry() -> None:
    for row in _rows():
        golden = _load_golden(row)
        asset_count = len(golden["physical_assets"])
        block_count = sum(len(asset["blocks"]) for asset in golden["physical_assets"])
        assert asset_count == int(row["physical_asset_count"])
        assert block_count == int(row["logical_block_count"])


def test_cpic_group_uses_official_listed_parent_identity() -> None:
    cpic_rows = [row for row in _rows() if row["company_id"] == "CPIC_GROUP"]
    assert len(cpic_rows) == 3
    for row in cpic_rows:
        golden = _load_golden(row)
        assert golden["legal_entity_name"] == "中国太平洋保险（集团）股份有限公司"
        assert golden["source"]["source_url"].startswith("https://www.cpic.com.cn/")


def test_china_life_2023_single_axis_is_not_forced_to_have_measurement() -> None:
    row = next(row for row in _rows() if row["golden_id"] == "CHINA_LIFE_2023_INVESTMENT_PORTFOLIO")
    golden = _load_golden(row)
    member_ids = {
        block["member_id"]
        for asset in golden["physical_assets"]
        for block in asset["blocks"]
    }
    assert member_ids == {"portfolio_by_category"}


def test_no_golden_derives_a_portfolio_total() -> None:
    for row in _rows():
        golden = _load_golden(row)
        assert golden["reported_portfolio_total"] == {
            "status": "DISCLOSED",
            "derivation_allowed": False,
        }
