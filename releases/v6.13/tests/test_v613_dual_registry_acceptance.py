from __future__ import annotations

from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import sqlite3

import jsonschema
import yaml

from golden_acceptance import _member_id, compare_child_capture_csv
from golden_identity import (
    build_identity_sidecar, load_yaml, sidecar_filename, validate_identity_sidecar,
    validate_identity_source_consistency,
)
from registry_acceptance import (
    AcceptanceStage,
    AcceptanceStatus,
    FINANCIAL_PROFILE,
    PORTFOLIO_PROFILE,
    ReadOnlyRegistrySnapshot,
    RegistryAcceptanceHarness,
    StageResult,
    compare_ui_offline_lanes,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = REPO_ROOT / "golden_corpus" / "v1.1.0"


def _sidecars():
    for profile in (PORTFOLIO_PROFILE, FINANCIAL_PROFILE):
        for company_id in profile.company_dirs:
            for year in (2023, 2024, 2025):
                directory = profile.filing_dir(CORPUS, company_id, year)
                yield profile, company_id, year, directory / sidecar_filename(profile.family)


def test_all_24_filing_profiles_have_strict_v12_identity() -> None:
    schema = json.loads(
        (CORPUS / "schema" / "golden_identity_v1_2.schema.json").read_text(encoding="utf-8")
    )
    cells = list(_sidecars())
    assert len(cells) == 24
    for profile, _, _, path in cells:
        payload = load_yaml(path)
        jsonschema.validate(payload, schema)
        directory = path.parent
        source_golden = load_yaml(directory / profile.golden_filename)
        filing_path = directory / "filing.yaml"
        filing = load_yaml(filing_path) if filing_path.is_file() else {}
        validation = validate_identity_source_consistency(
            payload, source_golden, filing=filing,
            expected_family=profile.family,
            expected_definition_id=profile.definition_id,
        )
        assert validation.status == "PASS", (path, validation.issues)
        assert validation.row_count > 0


def test_certified_supplementary_item_groups_are_not_dropped() -> None:
    for _, _, _, sidecar_path in _sidecars():
        if "financial_investment" not in sidecar_path.name:
            continue
        supplementary_path = sidecar_path.parent / "supplementary_golden_values.yaml"
        if not supplementary_path.is_file():
            continue
        supplementary = load_yaml(supplementary_path)
        assert supplementary.get("annotation_status") == "CERTIFIED_GOLDEN"
        expected = sum(
            len(value)
            for schedule in supplementary.get("supplementary_schedules") or []
            for key, value in schedule.items()
            if (key == "items" or key.startswith("items_")) and isinstance(value, list)
        )
        sidecar = load_yaml(sidecar_path)
        actual = sum(
            row.get("classification_axis") == "SUPPLEMENTARY_SCHEDULE"
            for row in sidecar.get("rows") or []
        )
        assert actual == expected, sidecar_path


def test_duplicate_row_identity_fails_closed() -> None:
    path = next(path for profile, _, _, path in _sidecars() if profile == PORTFOLIO_PROFILE)
    payload = load_yaml(path)
    payload["rows"].append(deepcopy(payload["rows"][0]))
    result = validate_identity_sidecar(payload)
    assert result.status == "FAIL"
    assert "DUPLICATE_GOLDEN_ROW_ID" in result.issues


def test_missing_stable_row_identity_fails_closed() -> None:
    path = next(path for profile, _, _, path in _sidecars() if profile == PORTFOLIO_PROFILE)
    payload = load_yaml(path)
    payload["rows"][0].pop("golden_row_id")
    result = validate_identity_sidecar(payload)
    assert result.status == "FAIL"
    assert any("GOLDEN_ROW_ID" in issue or "ROW_IDENTITY" in issue for issue in result.issues)


def test_dangling_parent_fails_closed() -> None:
    path = next(path for profile, _, _, path in _sidecars() if profile == PORTFOLIO_PROFILE)
    payload = load_yaml(path)
    payload["rows"][0]["parent_golden_row_id"] = "GROW_00000000000000000000"
    result = validate_identity_sidecar(payload)
    assert result.status == "FAIL"
    assert any(issue.startswith("DANGLING_GOLDEN_PARENT") for issue in result.issues)


def test_portfolio_identity_builder_closes_groups_and_keeps_final_total_at_root() -> None:
    golden = {
        "golden_id": "SYNTHETIC_PORTFOLIO_HIERARCHY",
        "company_id": "SYNTHETIC",
        "legal_entity_name": "测试保险",
        "report_year": 2025,
        "source_scope": "LISTED_PARENT_CONSOLIDATED",
        "source": {
            "canonical_pdf_filename": "synthetic.pdf",
            "pdf_sha256": "a" * 64,
            "page_count": 1,
            "source_type": "ANNUAL_REPORT",
        },
        "physical_assets": [{
            "asset_id": "SYNTHETIC_TABLE",
            "physical_page_number": 1,
            "printed_page_number": 1,
            "title": "投资组合",
            "unit": "RMB_MILLION",
            "blocks": [{
                "member_id": "portfolio_by_category",
                "classification_axis": "BY_INVESTMENT_OBJECT",
                "current_period": {"label": "2025年12月31日"},
                "comparative_period": {"label": "2024年12月31日"},
                "rows": [
                    {"row_order": 1, "raw_label": "甲类", "normalized_label": "甲类", "row_kind": "GROUP"},
                    {"row_order": 2, "raw_label": "甲项", "normalized_label": "甲项", "row_kind": "DATA"},
                    {"row_order": 3, "raw_label": "乙类", "normalized_label": "乙类", "row_kind": "GROUP"},
                    {"row_order": 4, "raw_label": "乙项", "normalized_label": "乙项", "row_kind": "DATA"},
                    {
                        "row_order": 5, "raw_label": "独立根项", "normalized_label": "独立根项",
                        "row_kind": "DATA", "parent_row_order": None,
                    },
                    {"row_order": 6, "raw_label": "投资资产合计", "normalized_label": "投资资产合计", "row_kind": "TOTAL"},
                ],
            }],
        }],
    }

    rows = build_identity_sidecar(
        family="investment_portfolio", golden=golden,
    )["rows"]
    by_label = {row["normalized_label"]: row for row in rows}

    assert by_label["甲类"]["parent_golden_row_id"] is None
    assert by_label["甲类"]["semantic_parent_path"] == "ROOT"
    assert by_label["甲项"]["parent_golden_row_id"] == by_label["甲类"]["golden_row_id"]
    assert by_label["甲项"]["semantic_parent_path"] == "甲类"
    assert by_label["乙类"]["parent_golden_row_id"] is None
    assert by_label["乙类"]["semantic_parent_path"] == "ROOT"
    assert by_label["乙项"]["parent_golden_row_id"] == by_label["乙类"]["golden_row_id"]
    assert by_label["乙项"]["semantic_parent_path"] == "乙类"
    assert by_label["独立根项"]["parent_golden_row_id"] is None
    assert by_label["独立根项"]["semantic_parent_path"] == "ROOT"
    assert by_label["投资资产合计"]["parent_golden_row_id"] is None
    assert by_label["投资资产合计"]["semantic_parent_path"] == "ROOT"


def test_golden_parent_id_and_semantic_path_must_agree() -> None:
    path = next(path for profile, _, _, path in _sidecars() if profile == PORTFOLIO_PROFILE)
    payload = load_yaml(path)
    root = next(row for row in payload["rows"] if not row.get("parent_golden_row_id"))
    root["semantic_parent_path"] = "错误父项"

    result = validate_identity_sidecar(payload)

    assert result.status == "FAIL"
    assert any(issue.startswith("GOLDEN_PARENT_PATH_MISMATCH") for issue in result.issues)


def test_golden_parent_must_share_physical_member_and_axis_scope() -> None:
    path = next(
        path for profile, company, year, path in _sidecars()
        if profile == PORTFOLIO_PROFILE and company == "PING_AN" and year == 2023
    )
    payload = load_yaml(path)
    category = next(
        row for row in payload["rows"]
        if row["member_table_id"] == "portfolio_by_category"
        and row.get("row_kind") == "GROUP"
    )
    measurement = next(
        row for row in payload["rows"]
        if row["member_table_id"] == "portfolio_by_measurement"
    )
    measurement["parent_golden_row_id"] = category["golden_row_id"]
    measurement["semantic_parent_path"] = category["normalized_label"]

    result = validate_identity_sidecar(payload)

    assert result.status == "FAIL"
    assert any(issue.startswith("GOLDEN_PARENT_SCOPE_MISMATCH") for issue in result.issues)


def test_explicit_source_parent_boundary_must_match_sidecar() -> None:
    directory = PORTFOLIO_PROFILE.filing_dir(CORPUS, "PING_AN", 2023)
    source = load_yaml(directory / PORTFOLIO_PROFILE.golden_filename)
    payload = load_yaml(directory / sidecar_filename(PORTFOLIO_PROFILE.family))
    category_rows = [
        row for row in payload["rows"]
        if row["member_table_id"] == "portfolio_by_category"
    ]
    target = next(row for row in category_rows if row["normalized_label"] == "长期股权投资")
    parent = next(row for row in category_rows if row["normalized_label"] == "股权型金融资产")
    target["parent_golden_row_id"] = parent["golden_row_id"]
    target["semantic_parent_path"] = parent["normalized_label"]

    result = validate_identity_source_consistency(
        payload, source,
        expected_family=PORTFOLIO_PROFILE.family,
        expected_definition_id=PORTFOLIO_PROFILE.definition_id,
    )

    assert result.status == "FAIL"
    assert any(issue.startswith("SOURCE_GOLDEN_PARENT_MISMATCH") for issue in result.issues)


def test_wrong_sha_and_cross_registry_fail_closed() -> None:
    path = next(path for profile, _, _, path in _sidecars() if profile == PORTFOLIO_PROFILE)
    payload = load_yaml(path)
    payload["filing_identity"]["pdf_sha256"] = "bad"
    payload["family"] = "financial_investment"
    result = validate_identity_sidecar(
        payload,
        expected_family="investment_portfolio",
        expected_definition_id="INVESTMENT_PORTFOLIO_V2",
    )
    assert result.status == "FAIL"
    assert "FILING_IDENTITY_INVALID_SHA256" in result.issues
    assert "CROSS_REGISTRY_GOLDEN_IDENTITY" in result.issues


def test_financial_identity_physical_page_mismatch_fails_corpus_preflight(
    tmp_path: Path,
) -> None:
    source = FINANCIAL_PROFILE.filing_dir(CORPUS, "CPIC", 2024)
    target = FINANCIAL_PROFILE.filing_dir(tmp_path, "CPIC", 2024)
    target.mkdir(parents=True)
    for filename in (
        "filing.yaml", "golden_values.yaml",
        sidecar_filename(FINANCIAL_PROFILE.family),
    ):
        shutil.copyfile(source / filename, target / filename)
    sidecar_path = target / sidecar_filename(FINANCIAL_PROFILE.family)
    sidecar = load_yaml(sidecar_path)
    sidecar["physical_tables"][0]["physical_page_number"] = 151
    sidecar_path.write_text(
        yaml.safe_dump(sidecar, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    db = tmp_path / "metadata.db"
    sqlite3.connect(db).close()

    result = RegistryAcceptanceHarness(
        corpus_root=tmp_path, metadata_db=db,
    ).evaluate(FINANCIAL_PROFILE, "CPIC", 2024)

    assert result.status == AcceptanceStatus.FAIL
    assert result.stages[0].reason_code == "GOLDEN_IDENTITY_V1_2_INVALID"
    assert any(
        issue.startswith("PHYSICAL_TABLE_PAGE_SOURCE_MISMATCH")
        for issue in result.stages[0].evidence["issues"]
    )


def test_financial_source_consistency_rejects_stale_member_and_primary_table() -> None:
    directory = FINANCIAL_PROFILE.filing_dir(CORPUS, "CPIC", 2024)
    source = load_yaml(directory / FINANCIAL_PROFILE.golden_filename)
    filing = load_yaml(directory / "filing.yaml")
    sidecar = load_yaml(directory / sidecar_filename(FINANCIAL_PROFILE.family))

    stale_member = deepcopy(next(
        row for row in sidecar["rows"] if row.get("row_kind") == "MEMBER"
    ))
    stale_member.update({
        "golden_row_id": "GROW_ffffffffffffffffffff",
        "member_table_id": "stale_legacy_member",
        "raw_label": "过期旧准则项目",
        "normalized_label": "过期旧准则项目",
    })
    sidecar["rows"].append(stale_member)
    sidecar["physical_tables"].append({
        "physical_table_id": f"{filing['filing_id']}::stale_legacy_member::PRIMARY",
        "physical_page_number": 1,
        "printed_page_number": 1,
        "title": "过期旧准则项目",
        "unit": "RMB_MILLION",
        "table_classification": "PRIMARY_TABLE",
    })

    result = validate_identity_source_consistency(
        sidecar, source, filing=filing, strict=True,
        expected_family=FINANCIAL_PROFILE.family,
        expected_definition_id=FINANCIAL_PROFILE.definition_id,
    )

    assert result.status == "FAIL"
    assert "SOURCE_GOLDEN_MEMBER_SET_MISMATCH" in result.issues
    assert "SOURCE_PRIMARY_TABLE_SET_MISMATCH" in result.issues


def test_financial_primary_identity_preserves_axis_and_parent_path() -> None:
    golden = {
        "schema_version": "1.1",
        "fixture_id": "FINANCIAL_PARENT_FIXTURE",
        "family": "financial_investment",
        "values": [{
            "member_id": "fvtpl_assets",
            "raw_label": "交易性金融资产",
            "current_amount_raw": "100",
            "child_table": {
                "classification": "PRIMARY_TABLE",
                "pdf_page_number": 10,
                "note_title": "交易性金融资产",
                "items": [
                    {
                        "raw_label": "上市", "amount_2025": "40",
                        "classification_axis": "LISTING_STATUS",
                    },
                    {
                        "raw_label": "债券", "amount_2025": "60",
                        "classification_axis": "ASSET_TYPE", "row_kind": "GROUP",
                    },
                    {
                        "raw_label": "政府债", "amount_2025": "60",
                        "classification_axis": "ASSET_TYPE", "parent_row_order": 2,
                    },
                    {
                        "raw_label": "合计", "amount_2025": "100",
                        "classification_axis": "ASSET_TYPE", "row_kind": "TOTAL",
                    },
                ],
            },
        }],
    }
    filing = {"filing_id": "CPIC_2025", "report_year": 2025}

    rows = build_identity_sidecar(
        family="financial_investment", golden=golden, filing=filing,
    )["rows"]
    primary = [row for row in rows if row["row_kind"] != "MEMBER"]
    by_label = {row["normalized_label"]: row for row in primary}

    assert by_label["上市"]["classification_axis"] == "LISTING_STATUS"
    assert by_label["债券"]["classification_axis"] == "ASSET_TYPE"
    assert by_label["政府债"]["parent_golden_row_id"] == by_label["债券"]["golden_row_id"]
    assert by_label["政府债"]["semantic_parent_path"] == "债券"
    assert by_label["合计"]["parent_golden_row_id"] is None
    assert by_label["合计"]["semantic_parent_path"] == "ROOT"


def test_financial_restated_comparative_period_identity_is_preserved() -> None:
    golden = {
        "schema_version": "1.1",
        "fixture_id": "FINANCIAL_RESTATED_FIXTURE",
        "family": "financial_investment",
        "values": [{
            "member_id": "legacy_fvtpl_assets",
            "raw_label": "以公允价值计量且其变动计入当期损益的金融资产",
            "comparative_amount_raw": "79465",
            "comparative_year": 2022,
            "status": "RESTATED_COMPARATIVE_PERIOD",
            "child_table": {
                "classification": "HISTORICAL_COMPARATIVE_TABLE",
                "pdf_page_number": 190,
                "note_title": "旧准则金融资产",
                "items": [{
                    "raw_label": "债权型投资小计",
                    "amount_2022_restated": "23593",
                }],
            },
        }],
    }
    filing = {"filing_id": "NCI_2023", "report_year": 2023}

    sidecar = build_identity_sidecar(
        family="financial_investment", golden=golden, filing=filing,
    )
    rows = sidecar["rows"]
    member = next(row for row in rows if row["row_kind"] == "HISTORICAL_MEMBER")
    item = next(row for row in rows if row.get("source_row_order") is not None)

    assert member["period_values"] == [{
        "period_role": "COMPARATIVE",
        "period_label": "2022年重述",
        "period_identity": "YEAR:2022",
        "measure": "AMOUNT",
        "unit": "SOURCE_DECLARED",
        "value": "79465",
    }]
    assert item["period_values"] == [{
        "period_role": "COMPARATIVE",
        "period_label": "2022年重述",
        "period_identity": "YEAR:2022",
        "measure": "AMOUNT",
        "unit": "SOURCE_DECLARED",
        "value": "23593",
    }]
    assert sidecar["physical_tables"][0]["table_classification"] == (
        "HISTORICAL_COMPARATIVE_TABLE"
    )
    assert sidecar["physical_tables"][0]["physical_table_id"].endswith(
        "::HISTORICAL_COMPARATIVE"
    )


def test_semantic_ui_offline_parity_ignores_volatile_ids() -> None:
    row = {
        "company_id": "PING_AN", "report_year": 2024,
        "family": "investment_portfolio", "physical_table_id": "T1",
        "member_table_id": "portfolio_by_category",
        "classification_axis": "BY_INVESTMENT_OBJECT",
        "semantic_row_key": "K1", "parent_semantic_row_key": None,
        "period_identity": "DATE:2024-12-31", "measure": "AMOUNT",
        "unit": "RMB_MILLION", "value": 1,
        "quality_status": "READY", "review_status": "CONFIRMED_AUTO",
        "merge_ready": True,
    }
    offline = dict(row, capture_id="OFFLINE", created_at="one")
    ui = dict(row, capture_id="UI", created_at="two")
    assert compare_ui_offline_lanes([offline], [ui]).status == AcceptanceStatus.PASS
    ui["value"] = 2
    assert compare_ui_offline_lanes([offline], [ui]).status == AcceptanceStatus.FAIL


def test_harness_consumes_isolated_ui_parity_evidence(tmp_path: Path) -> None:
    evidence = StageResult(
        AcceptanceStage.UI_PARITY,
        AcceptanceStatus.PASS,
        "UI_OFFLINE_SEMANTIC_PARITY",
        {"offline_count": 7, "ui_count": 7},
    )
    harness = RegistryAcceptanceHarness(
        corpus_root=tmp_path,
        metadata_db=tmp_path / "metadata.db",
        ui_parity_results={(PORTFOLIO_PROFILE.definition_id, "PING_AN", 2024): evidence},
    )

    assert harness._ui_parity_result(PORTFOLIO_PROFILE, "PING_AN", 2024) == evidence
    assert harness._ui_parity_result(
        PORTFOLIO_PROFILE, "PING_AN", 2023,
    ).status == AcceptanceStatus.NOT_RUN


def test_capture_snapshot_can_be_scoped_to_acceptance_lane_batch(tmp_path: Path) -> None:
    db = tmp_path / "metadata.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE capture_requests(
                request_id TEXT,research_batch_id TEXT,status TEXT,
                member_table_id TEXT,table_family_id TEXT,
                source_pdf_sha256 TEXT,source_pdf_id TEXT
            );
            CREATE TABLE capture_bundles(bundle_id TEXT,request_id TEXT);
            CREATE TABLE capture_bundle_children(
                bundle_id TEXT,capture_id TEXT,status TEXT,
                child_order INTEGER,payload_json TEXT
            );
            CREATE TABLE captures(
                capture_id TEXT,is_trashed INTEGER,merge_ready INTEGER,
                run_path TEXT,table_query TEXT
            );
        """)
        for suffix, batch in (("A", "OFFLINE_LANE"), ("B", "OLD_BATCH")):
            conn.execute(
                "INSERT INTO capture_requests VALUES(?,?,?,?,?,?,?)",
                (
                    f"REQ_{suffix}", batch, "SUCCESS", "debt_investment",
                    "financial_investment", "a" * 64, f"PDF_{suffix}",
                ),
            )
            conn.execute(
                "INSERT INTO capture_bundles VALUES(?,?)",
                (f"BUNDLE_{suffix}", f"REQ_{suffix}"),
            )
            conn.execute(
                "INSERT INTO capture_bundle_children VALUES(?,?,?,?,?)",
                (
                    f"BUNDLE_{suffix}", f"CAP_{suffix}", "CAPTURED", 0,
                    json.dumps({"role": "PRIMARY_TABLE"}),
                ),
            )
            conn.execute(
                "INSERT INTO captures VALUES(?,?,?,?,?)",
                (f"CAP_{suffix}", 0, 1, str(tmp_path), "债权投资"),
            )

    snapshot = ReadOnlyRegistrySnapshot(db).capture_snapshot(
        FINANCIAL_PROFILE, "a" * 64,
        research_batch_ids=["OFFLINE_LANE"],
    )

    assert snapshot["request_count"] == 1
    assert snapshot["captured_member_tables"] == ["debt_investment"]
    assert [row["capture_id"] for row in snapshot["captures"]] == ["CAP_A"]


def test_financial_snapshot_preserves_all_physical_blocks_in_certified_child_bundle(tmp_path: Path) -> None:
    db = tmp_path / "metadata.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            CREATE TABLE capture_requests(
                request_id TEXT,research_batch_id TEXT,status TEXT,
                member_table_id TEXT,table_family_id TEXT,
                source_pdf_sha256 TEXT,source_pdf_id TEXT
            );
            CREATE TABLE capture_bundles(bundle_id TEXT,request_id TEXT);
            CREATE TABLE capture_bundle_children(
                bundle_id TEXT,capture_id TEXT,status TEXT,
                child_order INTEGER,payload_json TEXT
            );
            CREATE TABLE captures(
                capture_id TEXT,is_trashed INTEGER,merge_ready INTEGER,
                run_path TEXT,table_query TEXT
            );
            INSERT INTO capture_requests VALUES(
                'REQ','LANE','SUCCESS','debt_investment',
                'financial_investment','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','PDF'
            );
            INSERT INTO capture_bundles VALUES('BUNDLE','REQ');
            INSERT INTO capture_bundle_children VALUES(
                'BUNDLE','PRIMARY','CAPTURED',0,'{"role":"PRIMARY_TABLE"}'
            );
            INSERT INTO capture_bundle_children VALUES(
                'BUNDLE','SECONDARY','CAPTURED',1,'{"role":"SECONDARY_TABLE"}'
            );
            INSERT INTO captures VALUES('PRIMARY',0,1,'x','按资产类型');
            INSERT INTO captures VALUES('SECONDARY',0,0,'y','按上市状态');
        """)

    snapshot = ReadOnlyRegistrySnapshot(db).capture_snapshot(
        FINANCIAL_PROFILE, "b" * 64, research_batch_ids=["LANE"],
    )

    assert snapshot["capture_count"] == 2
    assert snapshot["merge_ready_count"] == 1
    assert snapshot["physical_block_role_counts"] == {
        "PRIMARY_TABLE": 1,
        "SECONDARY_TABLE": 1,
    }
    assert [row["capture_id"] for row in snapshot["captures"]] == ["PRIMARY", "SECONDARY"]


def test_golden_comparator_accepts_stable_financial_member_identity() -> None:
    assert _member_id({"member_table": "fvtpl_assets"}) == "fvtpl_assets"
    assert _member_id({"member_table": "debt_investment"}) == "debt_investment"
    assert _member_id({"member_table": "other_debt_investment"}) == "other_debt_investment"
    assert _member_id({"member_table": "other_equity_investment"}) == "other_equity_investment"


def test_child_comparator_joins_multiple_physical_axes_by_certified_axis(tmp_path: Path) -> None:
    golden_dir = tmp_path / "companies" / "ping_an" / "2025"
    golden_dir.mkdir(parents=True)
    (golden_dir / "golden_values.yaml").write_text(
        yaml.safe_dump({
            "values": [{
                "member_id": "fvtpl_assets",
                "child_table": {"items": [
                    {
                        "raw_label": "合计", "amount_2025": "100",
                        "classification_axis": "ASSET_TYPE",
                    },
                    {
                        "raw_label": "合计", "amount_2025": "100",
                        "classification_axis": "LISTING_STATUS",
                    },
                ]},
            }],
        }, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    fieldnames = [
        "raw_item", "normalized_item", "data_year", "restated_flag",
        "classification_axis", "value_raw",
    ]
    paths = []
    for name, axis in (("asset.csv", "ASSET_TYPE"), ("listing.csv", "LISTING_STATUS")):
        path = tmp_path / name
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow({
                "raw_item": "合计", "normalized_item": "合计",
                "data_year": "2025", "restated_flag": "False",
                "classification_axis": axis, "value_raw": "100",
            })
        paths.append(path)

    result = compare_child_capture_csv(
        "中国平安", 2025, member_label="fvtpl_assets",
        raw_long_path=paths, root=tmp_path,
    )

    assert result["status"] == "MATCH"
    assert len(result["rows"]) == 2


def test_child_comparator_preserves_footnote_and_parent_path_label_semantics(tmp_path: Path) -> None:
    golden_dir = tmp_path / "companies" / "new_china_life" / "2025"
    golden_dir.mkdir(parents=True)
    (golden_dir / "golden_values.yaml").write_text(
        yaml.safe_dump({
            "values": [{
                "member_id": "other_debt_investment",
                "child_table": {"items": [
                    {"raw_label": "其他投资（注）", "amount_2025": "3,999"},
                    {"raw_label": "其中：成本", "amount_2025": "505,109"},
                    {"raw_label": "信托计划", "amount_2025": "–"},
                ]},
            }],
        }, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    path = tmp_path / "capture.csv"
    fieldnames = [
        "raw_item", "normalized_item", "parent_section", "data_year",
        "restated_flag", "classification_axis", "value_raw",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([
            {
                "raw_item": "其他投资（注）", "normalized_item": "其他投资",
                "parent_section": "", "data_year": "2025", "restated_flag": "False",
                "classification_axis": "ASSET_TYPE", "value_raw": "3,999",
            },
            {
                "raw_item": "成本", "normalized_item": "成本", "parent_section": "其中",
                "data_year": "2025", "restated_flag": "False",
                "classification_axis": "MEASUREMENT_COMPOSITION", "value_raw": "505,109",
            },
            {
                "raw_item": "信托计划", "normalized_item": "信托计划", "parent_section": "",
                "data_year": "2025", "restated_flag": "False",
                "classification_axis": "ASSET_TYPE", "value_raw": "–",
            },
        ])

    result = compare_child_capture_csv(
        "新华保险", 2025, member_label="other_debt_investment",
        raw_long_path=path, root=tmp_path,
    )

    assert result["status"] == "MATCH"
    assert len(result["rows"]) == 3


def test_child_comparator_supports_certified_measure_lanes(tmp_path: Path) -> None:
    golden_dir = tmp_path / "companies" / "china_life" / "2023"
    golden_dir.mkdir(parents=True)
    (golden_dir / "golden_values.yaml").write_text(
        yaml.safe_dump({
            "values": [{
                "member_id": "held_to_maturity_investments",
                "child_table": {"items": [{
                    "raw_label": "国债",
                    "amortized_cost_2023": "314,057",
                    "fair_value_2023": "359,637",
                }]},
            }],
        }, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    path = tmp_path / "capture.csv"
    fieldnames = [
        "raw_item", "normalized_item", "parent_section", "data_year",
        "restated_flag", "classification_axis", "measure", "value_raw",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for measure, value in (("摊余成本", "314,057"), ("公允价值", "359,637")):
            writer.writerow({
                "raw_item": "国债", "normalized_item": "国债", "parent_section": "债权型投资",
                "data_year": "2023", "restated_flag": "False",
                "classification_axis": "ASSET_TYPE", "measure": measure,
                "value_raw": value,
            })

    result = compare_child_capture_csv(
        "中国人寿", 2023, member_label="held_to_maturity_investments",
        raw_long_path=path, root=tmp_path,
    )

    assert result["status"] == "MATCH"
    assert len(result["rows"]) == 2


def test_child_comparator_maps_audited_implicit_total_role_to_golden_total(tmp_path: Path) -> None:
    golden_dir = tmp_path / "companies" / "ping_an" / "2023"
    golden_dir.mkdir(parents=True)
    (golden_dir / "golden_values.yaml").write_text(
        yaml.safe_dump({
            "values": [{
                "member_id": "debt_investment",
                "child_table": {"items": [
                    {"raw_label": "合计", "amount_2023": "1,243,353"},
                ]},
            }],
        }, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    path = tmp_path / "capture.csv"
    fieldnames = [
        "raw_item", "normalized_item", "row_role", "parent_section",
        "data_year", "restated_flag", "classification_axis", "value_raw",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow({
            "raw_item": "", "normalized_item": "债权投资总额",
            "row_role": "IMPLICIT_TOTAL", "parent_section": "",
            "data_year": "2023", "restated_flag": "False",
            "classification_axis": "LISTING_STATUS", "value_raw": "1,243,353",
        })

    result = compare_child_capture_csv(
        "中国平安", 2023, member_label="debt_investment",
        raw_long_path=path, root=tmp_path,
    )

    assert result["status"] == "MATCH"


def test_current_cpic_parent_pdf_does_not_silently_match_old_financial_golden(tmp_path: Path) -> None:
    db = tmp_path / "metadata.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE pdf_assets(
                pdf_id TEXT, filename TEXT, display_name TEXT, sha256 TEXT,
                company TEXT, document_year TEXT, size_bytes INTEGER, path TEXT,
                modified_at TEXT, created_at TEXT, updated_at TEXT, original_path TEXT,
                trash_path TEXT, lifecycle_status TEXT, trashed_at TEXT)"""
        )
        conn.execute(
            "INSERT INTO pdf_assets(pdf_id,sha256,lifecycle_status) VALUES(?,?,?)",
            ("CURRENT_CPIC_PARENT", "3b6117c82942" + "0" * 52, "ACTIVE"),
        )
    result = RegistryAcceptanceHarness(corpus_root=CORPUS, metadata_db=db).evaluate(
        FINANCIAL_PROFILE, "CPIC", 2024,
    )
    assert result.status == AcceptanceStatus.BLOCKED
    assert result.stages[0].reason_code == "BLOCKED_CANONICAL_PDF_IDENTITY_NOT_ACTIVE"
