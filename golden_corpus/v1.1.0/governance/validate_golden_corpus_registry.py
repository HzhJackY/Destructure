"""Validate the v1.1.0 Golden governance registries against source assets.

This is deliberately read-only.  It proves the registry is a projection of
independently adjudicated YAML and never upgrades a Golden fact from capture
output or from an omitted CSV row.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


COMPANY_DIRS = {
    "中国平安": "ping_an",
    "新华保险": "new_china_life",
    "中国太保": "cpic",
    "中国人寿": "china_life",
    "中国人保": "picc",
    "中国财险": "picc_pnc",
    "中国再保": "china_re",
    "阳光保险": "sunshine_insurance",
    "众安在线": "zhongan_online",
    "友邦保险": "aia",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {str(key).strip(): str(value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle, skipinitialspace=True)
        ]


def read_yaml(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def count_child_values(items: list[dict[str, Any]], year: str) -> tuple[int, int, int, int]:
    total = current = comparative = restated = 0
    for item in items:
        for key, value in item.items():
            if key == "raw_label" or value is None:
                continue
            total += 1
            if "restated" in key:
                restated += 1
            elif year in key:
                current += 1
            else:
                comparative += 1
    return total, current, comparative, restated


def count_schedule_values(schedule: dict[str, Any], report_year: str) -> tuple[int, int, int, int]:
    total = current = comparative = restated = 0
    title_year = next(iter(re.findall(r"(20\d{2})年度", str(schedule.get("schedule_title") or ""))), "")
    declared_period = str(schedule.get("period") or title_year)
    for key, items in schedule.items():
        if not key.startswith("items"):
            continue
        bucket_is_current = str(report_year) in key or (
            key == "items" and declared_period == str(report_year)
        )
        for item in items or []:
            for column, value in item.items():
                if column == "raw_label" or value is None:
                    continue
                total += 1
                if "restated" in key or "restated" in column:
                    restated += 1
                elif bucket_is_current:
                    current += 1
                else:
                    comparative += 1
    return total, current, comparative, restated


def expected_table_segments(root: Path, filing_id: str, company_dir: str, year: str) -> list[dict[str, Any]]:
    base = root / "companies" / company_dir / year
    expected: list[dict[str, Any]] = []
    primary_path = base / "golden_values.yaml"
    if primary_path.exists():
        for value in read_yaml(primary_path).get("values") or []:
            table = value.get("child_table") or {}
            if not table:
                continue
            total, current, comparative, restated = count_child_values(table.get("items") or [], year)
            expected.append({
                "filing_id": filing_id,
                "member_id": str(value.get("member_id") or ""),
                "table_classification": "PRIMARY_TABLE",
                "pdf_page_start": str(table.get("pdf_page_number") or ""),
                "golden_asset_path": f"companies/{company_dir}/{year}/golden_values.yaml",
                "value_assertion_count": total,
                "current_period_value_assertion_count": current,
                "comparative_period_value_assertion_count": comparative,
                "restated_period_value_assertion_count": restated,
            })
    supplementary_path = base / "supplementary_golden_values.yaml"
    if supplementary_path.exists():
        for schedule in read_yaml(supplementary_path).get("supplementary_schedules") or []:
            total, current, comparative, restated = count_schedule_values(schedule, year)
            schedule_id = str(schedule.get("schedule_id") or "")
            member_id = str(schedule.get("member_id") or "") or (
                "other_debt_investment" if schedule_id.startswith("other_debt") else (
                    "debt_investment" if schedule_id.startswith("debt") else (
                        "available_for_sale_assets" if schedule_id.startswith("available_for_sale") else "held_to_maturity_investments"
                    )
                )
            )
            expected.append({
                "filing_id": filing_id,
                "member_id": member_id,
                "table_classification": "SUPPLEMENTARY_TABLE",
                "pdf_page_start": str(schedule.get("pdf_page_number") or ""),
                "golden_asset_path": f"companies/{company_dir}/{year}/supplementary_golden_values.yaml",
                "value_assertion_count": total,
                "current_period_value_assertion_count": current,
                "comparative_period_value_assertion_count": comparative,
                "restated_period_value_assertion_count": restated,
            })
    return expected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    errors: list[str] = []

    inventory = read_csv(root / "filing_inventory.csv")
    exclusions = read_csv(root / "filing_exclusions.csv")
    coverage = read_csv(root / "golden_coverage_registry.csv")
    segments = read_csv(root / "golden_table_segment_registry.csv")
    archived = read_csv(root / "migration" / "filing_inventory.pre_governance_v1.1.0.csv")

    if len(inventory) != 12:
        errors.append(f"inventory target count is {len(inventory)}, expected 12")
    if len(archived) != 13 or len(exclusions) != 1:
        errors.append("migration archive/exclusion cardinality is not 13/1")
    inventory_keys = {(row["company"], row["report_year"]) for row in inventory}
    if len(inventory_keys) != len(inventory):
        errors.append("inventory has duplicate company/year identities")
    if any(row["canonical_for_testing"].lower() != "true" for row in inventory):
        errors.append("inventory contains a non-canonical filing")
    if any((row["company"], row["report_year"]) in inventory_keys for row in exclusions):
        errors.append("an exclusion is still present in the canonical inventory")

    coverage_by_filing = {row["filing_id"]: row for row in coverage}
    if len(coverage_by_filing) != 12:
        errors.append("coverage registry does not contain exactly one row per canonical filing")
    if len({row["physical_segment_id"] for row in segments}) != len(segments):
        errors.append("physical segment IDs are not unique")
    if len({row["logical_table_id"] for row in segments}) != len(segments):
        errors.append("logical table IDs are not unique for the one-segment backfill")

    for row in segments:
        classification = row["table_classification"]
        is_continuation = classification == "CONTINUATION_SEGMENT"
        if is_continuation:
            if not row["continuation_of_physical_segment_id"] or row["continuation_relation_status"] != "CERTIFIED_GOLDEN":
                errors.append(f"{row['physical_segment_id']} is a continuation without certified parent relation")
        elif row["continuation_relation_status"] != "NOT_APPLICABLE":
            errors.append(f"{row['physical_segment_id']} has an invalid continuation relation")
        if classification == "SUPPLEMENTARY_TABLE" and not row["associated_primary_logical_table_id"]:
            errors.append(f"{row['physical_segment_id']} lacks its associated primary logical table")
        values = [int(row[key]) for key in (
            "current_period_value_assertion_count", "comparative_period_value_assertion_count", "restated_period_value_assertion_count"
        )]
        if int(row["value_assertion_count"]) != sum(values):
            errors.append(f"{row['physical_segment_id']} value assertion buckets do not reconcile")

    segments_by_filing: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in segments:
        segments_by_filing[row["filing_id"]].append(row)

    for inventory_row in inventory:
        company = inventory_row["company"]
        year = inventory_row["report_year"]
        company_dir = COMPANY_DIRS.get(company)
        filing_id = f"{read_yaml(root / 'companies' / company_dir / year / 'filing.yaml')['company_id']}_{year}"
        coverage_row = coverage_by_filing.get(filing_id)
        if coverage_row is None:
            errors.append(f"missing coverage row for {filing_id}")
            continue
        filing = read_yaml(root / "companies" / company_dir / year / "filing.yaml")
        if str(filing.get("pdf_sha256")) != inventory_row["pdf_sha256"]:
            errors.append(f"{filing_id} SHA does not reconcile to filing identity")
        if str(filing.get("page_count")) != inventory_row["page_count"]:
            errors.append(f"{filing_id} page count does not reconcile to filing identity")
        anchors = root / "companies" / company_dir / year / "page_anchors.yaml"
        pattern = root / "companies" / company_dir / year / "disclosure_pattern.yaml"
        for path, status_key in ((anchors, "page_anchor_status"), (pattern, "disclosure_pattern_status")):
            expected_status = "CERTIFIED_GOLDEN" if path.exists() else "MISSING"
            if coverage_row[status_key] != expected_status:
                errors.append(f"{filing_id} {status_key} disagrees with source asset")
        anchor_data = read_yaml(anchors)
        crop = str(anchor_data.get("page_image_crop") or "")
        crop_status = "AVAILABLE" if crop and (root / crop).is_file() else "MISSING"
        if coverage_row["evidence_crops_status"] != crop_status:
            errors.append(f"{filing_id} crop status disagrees with anchor evidence")

        primary_yaml = root / "companies" / company_dir / year / "golden_values.yaml"
        main_assertions = len(read_yaml(primary_yaml).get("values") or []) if primary_yaml.exists() else 0
        expected_main_status = "CERTIFIED_GOLDEN" if primary_yaml.exists() else "MISSING"
        if coverage_row["main_statement_value_golden_status"] != expected_main_status or int(coverage_row["main_statement_value_assertion_count"]) != main_assertions:
            errors.append(f"{filing_id} main-statement coverage disagrees with golden_values.yaml")

        expected = expected_table_segments(root, filing_id, company_dir, year)
        actual = segments_by_filing[filing_id]
        expected_keys = {
            tuple(str(item[key]) for key in ("member_id", "table_classification", "pdf_page_start", "golden_asset_path", "value_assertion_count", "current_period_value_assertion_count", "comparative_period_value_assertion_count", "restated_period_value_assertion_count"))
            for item in expected
        }
        actual_keys = {
            tuple(item[key] for key in ("member_id", "table_classification", "pdf_page_start", "golden_asset_path", "value_assertion_count", "current_period_value_assertion_count", "comparative_period_value_assertion_count", "restated_period_value_assertion_count"))
            for item in actual
        }
        if expected_keys != actual_keys:
            errors.append(f"{filing_id} table/segment backfill does not reconcile to YAML assets")
        primary = [row for row in actual if row["table_classification"] == "PRIMARY_TABLE"]
        supplementary = [row for row in actual if row["table_classification"] == "SUPPLEMENTARY_TABLE"]
        continuations = [row for row in actual if row["table_classification"] == "CONTINUATION_SEGMENT"]
        aggregate = {
            "primary_child_table_count": len(primary),
            "primary_child_value_assertion_count": sum(int(row["value_assertion_count"]) for row in primary),
            "supplementary_child_table_count": len(supplementary),
            "supplementary_child_value_assertion_count": sum(int(row["value_assertion_count"]) for row in supplementary),
            "continuation_segment_count": len(continuations),
            "continuation_value_assertion_count": sum(int(row["value_assertion_count"]) for row in continuations),
            "current_period_value_assertion_count": sum(int(row["current_period_value_assertion_count"]) for row in actual),
            "comparative_period_value_assertion_count": sum(int(row["comparative_period_value_assertion_count"]) for row in actual),
            "restated_period_value_assertion_count": sum(int(row["restated_period_value_assertion_count"]) for row in actual),
        }
        for key, value in aggregate.items():
            if int(coverage_row[key]) != value:
                errors.append(f"{filing_id} {key} is {coverage_row[key]}, expected {value}")

    if errors:
        print("GOLDEN_REGISTRY_INVALID")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("GOLDEN_REGISTRY_VALID")
    print(f"canonical_filings={len(inventory)} exclusions={len(exclusions)} table_segments={len(segments)}")
    print(
        "primary_segments={} supplementary_segments={} continuation_segments={}".format(
            sum(row["table_classification"] == "PRIMARY_TABLE" for row in segments),
            sum(row["table_classification"] == "SUPPLEMENTARY_TABLE" for row in segments),
            sum(row["table_classification"] == "CONTINUATION_SEGMENT" for row in segments),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
