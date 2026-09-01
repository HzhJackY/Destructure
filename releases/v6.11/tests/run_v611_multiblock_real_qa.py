from __future__ import annotations

import gc
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

RELEASE_ROOT = Path(__file__).resolve().parents[1]
if str(RELEASE_ROOT) not in sys.path:
    sys.path.insert(0, str(RELEASE_ROOT))

from compound_note_engine import materialize_block_result, segment_table_blocks
from metadata_registry import MetadataRegistry
from note_target_resolver import NoteReferenceResolver
from table_capture import capture_named_table, capture_to_long_df, write_capture_artifacts
from table_merge import (
    apply_mapping,
    assign_conditional_source_keys,
    build_mapping_queue,
    materialize_canonical,
)


BLOCK_FIELDS = [
    "container_id",
    "table_block_id",
    "block_order",
    "classification_axis",
    "block_role",
    "block_terminal_type",
]

EXPECTED_LOGICAL_ROWS = [
    ("债券", "ASSET_TYPE"),
    ("政府债", "ASSET_TYPE"),
    ("金融债", "ASSET_TYPE"),
    ("企业债", "ASSET_TYPE"),
    ("债权计划", "ASSET_TYPE"),
    ("理财产品投资", "ASSET_TYPE"),
    ("合计", "ASSET_TYPE"),
    ("其中－摊余成本", "MEASUREMENT_COMPOSITION"),
    ("其中－累计公允价值变动", "MEASUREMENT_COMPOSITION"),
    ("上市", "LISTING_STATUS"),
    ("非上市", "LISTING_STATUS"),
    ("IMPLICIT_FINAL_TOTAL", "LISTING_STATUS"),
]

EXPECTED_AMOUNTS = {
    "政府债": {"2025": 2_620_241.0, "2024": 2_493_010.0},
    "金融债": {"2025": 362_548.0, "2024": 410_742.0},
    "企业债": {"2025": 83_453.0, "2024": 95_586.0},
    "债权计划": {"2025": 89_704.0, "2024": 102_884.0},
    "理财产品投资": {"2025": 75_489.0, "2024": 84_715.0},
    "合计": {"2025": 3_231_435.0, "2024": 3_186_937.0},
    "其中－摊余成本": {"2025": 2_801_516.0, "2024": 2_591_775.0},
    "其中－累计公允价值变动": {"2025": 429_919.0, "2024": 595_162.0},
    "上市": {"2025": 722_809.0, "2024": 398_075.0},
    "非上市": {"2025": 2_508_626.0, "2024": 2_788_862.0},
    "IMPLICIT_FINAL_TOTAL": {"2025": 3_231_435.0, "2024": 3_186_937.0},
}


def _logical_label(row: Any) -> str | None:
    if row.row_type in {"MEMO_TEXT", "NOTE_TEXT"}:
        return None
    raw = str(row.raw_item or "").strip()
    if raw.rstrip("：:") == "其中" and not row.cells:
        return None
    if row.row_role == "IMPLICIT_TOTAL" and not raw:
        return "IMPLICIT_FINAL_TOTAL"
    if str(row.parent_section or "").rstrip("：:") == "其中":
        return f"其中{raw}"
    return raw


def _as_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return " | ".join(str(item) for item in value)
    return str(value)


def _amounts_match_expected(
    logical_label: str,
    observed: dict[str, float | None],
) -> bool:
    expected = EXPECTED_AMOUNTS.get(logical_label)
    if expected is None:
        return not observed or all(value is None for value in observed.values())
    if set(observed) != set(expected):
        return False
    return all(
        observed[year] is not None
        and abs(float(observed[year]) - expected_value) <= 1e-9
        for year, expected_value in expected.items()
    )


def _persist_and_read_registry_blocks(
    registry: MetadataRegistry,
    container: Any,
    blocks: list[Any],
) -> list[dict[str, Any]]:
    """Exercise the real table_blocks row contract in an isolated registry."""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with registry.connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO note_containers
            (container_id,source_pdf_id,source_pdf_sha256,source_pdf_path,
             note_reference,note_title,start_pdf_page,end_pdf_page,
             context_json,layout_graph_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                container.container_id,
                None,
                container.source_pdf_sha256,
                None,
                container.note_reference,
                container.note_title,
                container.start_pdf_page,
                container.end_pdf_page,
                "{}",
                json.dumps(container.layout_evidence, ensure_ascii=False),
                now,
            ),
        )
        for block in blocks:
            connection.execute(
                """
                INSERT INTO table_blocks
                (block_id,container_id,block_order,block_title,block_role,
                 classification_axis,block_terminal_type,start_pdf_page,
                 end_pdf_page,bbox_json,header_topology_json,
                 semantic_graph_json,reconciliation_json,quality_status,
                 status,evidence_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    block.block_id,
                    container.container_id,
                    block.block_order,
                    block.title,
                    block.role,
                    block.classification_axis,
                    block.block_terminal_type,
                    block.start_pdf_page,
                    block.end_pdf_page,
                    json.dumps(block.bbox, ensure_ascii=False),
                    json.dumps(block.header_topology, ensure_ascii=False),
                    json.dumps(block.semantic_graph, ensure_ascii=False),
                    json.dumps(block.reconciliation, ensure_ascii=False),
                    block.quality_status,
                    "CAPTURED",
                    json.dumps(block.evidence, ensure_ascii=False),
                    now,
                ),
            )
        persisted = connection.execute(
            """
            SELECT block_id, block_id AS table_block_id, container_id,
                   block_order, classification_axis, block_role,
                   block_terminal_type
            FROM table_blocks
            WHERE container_id=?
            ORDER BY block_order
            """,
            (container.container_id,),
        ).fetchall()
    return [dict(row) for row in persisted]


def main() -> None:
    release_root = Path(__file__).resolve().parents[1]
    repo_root = Path(__file__).resolve().parents[3]
    qa_root = repo_root / "output_agent_runs" / "v611_codex_takeover"
    run_root = (
        repo_root
        / "output"
        / "_agent_runs"
        / "v611_codex_takeover"
        / "multiblock_impl"
    )
    qa_root.mkdir(parents=True, exist_ok=True)
    run_root.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []

    def record(
        check_id: str,
        layer: str,
        expected: Any,
        actual: Any,
        passed: bool,
        evidence: str,
    ) -> None:
        checks.append(
            {
                "check_id": check_id,
                "layer": layer,
                "expected": _as_text(expected),
                "actual": _as_text(actual),
                "status": "PASS" if passed else "FAIL",
                "evidence": evidence,
            }
        )

    pdf = repo_root / "docu" / "中国平安2025年报.pdf"
    if not pdf.exists():
        raise FileNotFoundError(f"真实年报不存在：{pdf}")

    resolver = NoteReferenceResolver()
    candidates = resolver.candidates_from_pdf(
        pdf,
        note_reference="附注八-11",
        member_table="其他债权投资",
    )
    target = resolver.certify(candidates[0])
    result = capture_named_table(
        pdf,
        "其他债权投资",
        note_number="附注八-11",
        start_page_override=target["confirmed_note_pdf_page_index"],
        max_pages=8,
        allow_legacy_fallback=False,
    )
    container, blocks = segment_table_blocks(result)

    actual_axes = [block.classification_axis for block in blocks]
    actual_terminals = [block.block_terminal_type for block in blocks]
    expected_axes = [
        "ASSET_TYPE",
        "MEASUREMENT_COMPOSITION",
        "LISTING_STATUS",
    ]
    expected_terminals = ["LOCAL_TOTAL", "NONE", "FINAL_TOTAL"]
    record(
        "BLOCK_COUNT_THREE",
        "compound_note_engine",
        3,
        len(blocks),
        len(blocks) == 3,
        f"container_id={container.container_id}",
    )
    record(
        "CLASSIFICATION_AXIS_ORDER",
        "compound_note_engine",
        expected_axes,
        actual_axes,
        actual_axes == expected_axes,
        "真实附注按资产类型、计量构成、上市状态分块",
    )
    record(
        "BLOCK_TERMINAL_TYPES",
        "compound_note_engine",
        expected_terminals,
        actual_terminals,
        actual_terminals == expected_terminals,
        "局部合计不终止 Note Container；最终隐式合计只终止最后子块",
    )
    record(
        "ROI_NO_PREPARSER_HARD_BREAK",
        "spatial_table_capture",
        "primary_table_end_applied=False; post_total_disclosure_not_merged=False",
        (
            f"primary_table_end_applied="
            f"{result.stats.get('primary_table_end_applied')}; "
            f"post_total_disclosure_not_merged="
            f"{result.stats.get('post_total_disclosure_not_merged')}"
        ),
        result.stats.get("primary_table_end_applied") is False
        and result.stats.get("post_total_disclosure_not_merged") is False,
        "peer-heading ROI 内全部行进入语义解析器",
    )

    frames: list[pd.DataFrame] = []
    artifact_json_field_checks: list[bool] = []
    artifact_long_field_checks: list[bool] = []
    artifact_count = 0

    with tempfile.TemporaryDirectory(
        prefix="v611_pingan_other_debt_",
        dir=run_root,
    ) as temporary_directory:
        isolated_root = Path(temporary_directory)
        record(
            "ISOLATED_OUTPUT_ROOT",
            "runtime_safety",
            str(run_root),
            str(isolated_root.parent),
            isolated_root.parent == run_root,
            "子块 artifact 仅写入任务临时目录，未使用生产 DATA_HOME",
        )

        registry = MetadataRegistry(isolated_root / "metadata.db")
        persisted_registry_rows = _persist_and_read_registry_blocks(
            registry,
            container,
            blocks,
        )
        expected_registry_rows = {
            block.block_id: (
                container.container_id,
                block.block_order,
                block.classification_axis,
                block.role,
                block.block_terminal_type,
            )
            for block in blocks
        }
        actual_registry_rows = {
            row["block_id"]: (
                row["container_id"],
                row["block_order"],
                row["classification_axis"],
                row["block_role"],
                row["block_terminal_type"],
            )
            for row in persisted_registry_rows
        }
        registry_ok = (
            len(persisted_registry_rows) == len(blocks)
            and actual_registry_rows == expected_registry_rows
        )
        record(
            "REGISTRY_BLOCK_FIELDS",
            "metadata_registry",
            expected_registry_rows,
            actual_registry_rows,
            registry_ok,
            "临时 SQLite table_blocks 实际 INSERT/SELECT 行级回读",
        )

        for block in blocks:
            child = materialize_block_result(result, block)
            artifact_paths = write_capture_artifacts(
                isolated_root / f"block_{block.block_order}",
                child,
            )
            artifact_count += len(artifact_paths)
            payload = json.loads(
                Path(artifact_paths["result_json"]).read_text(encoding="utf-8")
            )
            artifact_json_field_checks.extend(
                all(field in row for field in BLOCK_FIELDS)
                for row in payload["rows"]
            )

            frame = capture_to_long_df(child)
            artifact_long_field_checks.append(
                set(BLOCK_FIELDS).issubset(frame.columns)
            )
            frame["capture_run_id"] = (
                f"PINGAN_2025_OTHER_DEBT_BLOCK_{block.block_order}"
            )
            frame["company"] = "中国平安"
            frame["document_year"] = "2025"
            frame["report_year"] = "2025"
            frame["table_id"] = "OTHER_DEBT_INVESTMENT"
            frame["table_family"] = "FINANCIAL_INVESTMENT"
            frame["member_table"] = "其他债权投资"
            frame["member_table_role"] = "COMPONENT"
            frame["source_table_title"] = "其他债权投资"
            frame["note_reference"] = "附注八-11"
            frame["source_pdf"] = str(pdf)
            frame["period_type"] = "ANNUAL"
            frames.append(frame)

        record(
            "CHILD_JSON_BLOCK_FIELDS",
            "child_artifacts",
            f"{len(BLOCK_FIELDS)} fields on every child JSON row",
            f"rows_checked={len(artifact_json_field_checks)}",
            bool(artifact_json_field_checks)
            and all(artifact_json_field_checks),
            f"isolated_artifact_count={artifact_count}",
        )
        record(
            "CANONICAL_LONG_BLOCK_FIELDS",
            "canonical_long",
            BLOCK_FIELDS,
            BLOCK_FIELDS
            if artifact_long_field_checks and all(artifact_long_field_checks)
            else "missing",
            bool(artifact_long_field_checks)
            and all(artifact_long_field_checks),
            "capture_to_long_df(child)",
        )

        raw_long = pd.concat(frames, ignore_index=True)
        raw_long = assign_conditional_source_keys(raw_long)
        mapping_queue = build_mapping_queue(
            raw_long,
            table_id="OTHER_DEBT_INVESTMENT",
        )
        mapped = apply_mapping(raw_long, mapping_queue)
        resolved, canonical_wide, conflicts = materialize_canonical(mapped)

        numeric_count = int(raw_long["value"].notna().sum())
        resolved_count = len(resolved)
        record(
            "MERGE_NUMERIC_OBSERVATION_COUNT",
            "table_merge",
            numeric_count,
            resolved_count,
            resolved_count == numeric_count,
            (
                f"mapping_queue={len(mapping_queue)}; "
                f"canonical_wide={len(canonical_wide)}"
            ),
        )
        record(
            "MERGE_BLOCK_FIELDS",
            "table_merge",
            BLOCK_FIELDS,
            [field for field in BLOCK_FIELDS if field in resolved.columns],
            set(BLOCK_FIELDS).issubset(resolved.columns)
            and set(BLOCK_FIELDS).issubset(canonical_wide.columns),
            "apply_mapping -> materialize_canonical",
        )
        record(
            "MERGE_AXIS_PRESERVATION",
            "table_merge",
            expected_axes,
            sorted(
                resolved["classification_axis"].dropna().unique().tolist(),
                key=expected_axes.index,
            ),
            set(resolved["classification_axis"]) == set(expected_axes),
            "Canonical Research Long 保留三种 classification_axis",
        )
        record(
            "MERGE_CONFLICT_FREE",
            "table_merge",
            0,
            len(conflicts),
            conflicts.empty,
            "真实单份年报三子块不发生错误跨块折叠",
        )

        annotated_rows = [
            row
            for block in sorted(blocks, key=lambda item: item.block_order)
            for row in block.rows
        ]
        logical_rows = [
            (row, label)
            for row in annotated_rows
            if (label := _logical_label(row)) is not None
        ]
        actual_logical = [label for _, label in logical_rows]
        expected_logical = [item[0] for item in EXPECTED_LOGICAL_ROWS]
        record(
            "REAL_LOGICAL_ROWS_12",
            "real_pdf_capture",
            expected_logical,
            actual_logical,
            actual_logical == expected_logical,
            f"source_page={result.start_page}; rows={len(actual_logical)}",
        )
        actual_years = [column.year for column in result.columns]
        record(
            "REAL_TWO_YEAR_COLUMNS",
            "real_pdf_capture",
            ["2025", "2024"],
            actual_years,
            actual_years == ["2025", "2024"],
            "年度列来自真实表头，不从公司或页码硬编码",
        )

        column_by_ordinal = {column.ordinal: column for column in result.columns}
        row_qa: list[dict[str, Any]] = []
        for index, (row, label) in enumerate(logical_rows):
            expected_label = (
                EXPECTED_LOGICAL_ROWS[index][0]
                if index < len(EXPECTED_LOGICAL_ROWS)
                else ""
            )
            expected_axis = (
                EXPECTED_LOGICAL_ROWS[index][1]
                if index < len(EXPECTED_LOGICAL_ROWS)
                else ""
            )
            values = {
                str(column_by_ordinal[cell.column_ordinal].year): cell.parsed_number
                for cell in row.cells
                if cell.column_ordinal in column_by_ordinal
            }
            observed_amounts = (
                {
                    "2025": values.get("2025"),
                    "2024": values.get("2024"),
                }
                if values
                else {}
            )
            expected_amounts = EXPECTED_AMOUNTS.get(label, {})
            passed = (
                label == expected_label
                and row.classification_axis == expected_axis
                and row.container_id == container.container_id
                and bool(row.table_block_id)
                and _amounts_match_expected(
                    label,
                    {
                        "2025": values.get("2025"),
                        "2024": values.get("2024"),
                    }
                    if values
                    else {},
                )
            )
            row_qa.append(
                {
                    "logical_order": index + 1,
                    "logical_row": label,
                    "expected_logical_row": expected_label,
                    "row_type": row.row_type,
                    "row_role": row.row_role,
                    "source_page": row.page,
                    "container_id": row.container_id,
                    "table_block_id": row.table_block_id,
                    "block_order": row.block_order,
                    "classification_axis": row.classification_axis,
                    "expected_axis": expected_axis,
                    "block_role": row.block_role,
                    "block_terminal_type": row.block_terminal_type,
                    "value_2025": values.get("2025"),
                    "value_2024": values.get("2024"),
                    "expected_value_2025": expected_amounts.get("2025"),
                    "expected_value_2024": expected_amounts.get("2024"),
                    "amount_oracle_pass": _amounts_match_expected(
                        label,
                        observed_amounts,
                    ),
                    "status": "PASS" if passed else "FAIL",
                }
            )

        del frame
        del raw_long
        del mapping_queue
        del mapped
        del resolved
        del canonical_wide
        del conflicts
        gc.collect()

    checks_df = pd.DataFrame(checks)
    row_qa_df = pd.DataFrame(row_qa)
    checks_path = qa_root / "multiblock_capture_qa.csv"
    real_path = qa_root / "pingan_other_debt_real_capture_qa.csv"
    checks_df.to_csv(checks_path, index=False, encoding="utf-8-sig")
    row_qa_df.to_csv(real_path, index=False, encoding="utf-8-sig")

    failed_checks = checks_df.loc[checks_df["status"] != "PASS", "check_id"].tolist()
    failed_rows = row_qa_df.loc[
        row_qa_df["status"] != "PASS", "logical_order"
    ].tolist()
    print(
        json.dumps(
            {
                "multiblock_capture_qa": str(checks_path),
                "pingan_other_debt_real_capture_qa": str(real_path),
                "checks": len(checks_df),
                "logical_rows": len(row_qa_df),
                "failed_checks": failed_checks,
                "failed_rows": failed_rows,
            },
            ensure_ascii=False,
        )
    )
    del checks_df
    del row_qa_df
    del frames
    gc.collect()
    if failed_checks or failed_rows:
        raise AssertionError(
            f"真实多 block QA 失败：checks={failed_checks}, rows={failed_rows}"
        )


if __name__ == "__main__":
    main()
