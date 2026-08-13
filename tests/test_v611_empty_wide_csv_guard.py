"""空/仅 BOM 的捕获 CSV 防护回归测试（memo-only 表块不再使 job 失败）。

背景：其他权益工具投资 2023 附注页含纯备忘行块（无金额列），其
table_raw_wide.csv 为 utf-8-sig 空 DataFrame 写出的 5 字节文件，
``pd.read_csv`` 会抛 EmptyDataError 导致整条抓取 job FAILED。
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capture_library import _read_csv_optional, _rewrite_capture_excel
from reconciliation import write_reconciliation_audit


def test_read_csv_optional_missing_file_returns_empty() -> None:
    df = _read_csv_optional(Path("definitely_missing.csv"))
    assert isinstance(df, pd.DataFrame) and df.empty


def test_read_csv_optional_5byte_bom_only_file_returns_empty(tmp_path) -> None:
    # utf-8-sig 空 DataFrame 写出的是 BOM+CRLF（5 字节），无任何列
    path = tmp_path / "table_raw_wide.csv"
    path.write_bytes(b"\xef\xbb\xbf\r\n")
    assert path.stat().st_size == 5
    df = _read_csv_optional(path)
    assert isinstance(df, pd.DataFrame) and df.empty


def test_read_csv_optional_normal_file_parses() -> None:
    path = Path(__file__).resolve().parent / "fixtures" / "not_present.csv"
    assert not path.exists()
    # 用真实临时文件验证正常解析
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "ok.csv"
        p.write_text("a,b\n1,2\n", encoding="utf-8")
        df = _read_csv_optional(p)
        assert list(df.columns) == ["a", "b"]
        assert len(df) == 1


def test_rewrite_capture_excel_tolerates_5byte_wide_csv(tmp_path) -> None:
    # 复刻 b3 memo-only 块的文件形态：wide 5 字节，long 有内容
    run = tmp_path / "run"
    run.mkdir()
    (run / "table_raw_wide.csv").write_bytes(b"\xef\xbb\xbf\r\n")
    (run / "machine_capture_full_wide.csv").write_bytes(b"\xef\xbb\xbf\r\n")
    (run / "table_raw_long.csv").write_text(
        "row_order,row_type,normalized_item,raw_item\n"
        "15,MEMO_TEXT,见附注七、40。,见附注七、40。\n",
        encoding="utf-8-sig",
    )
    (run / "machine_capture_full_long.csv").write_text(
        "row_order,row_type,normalized_item,raw_item\n"
        "15,MEMO_TEXT,见附注七、40。,见附注七、40。\n",
        encoding="utf-8-sig",
    )
    (run / "table_item_dictionary.csv").write_text(
        "normalized_item,example_raw_item\n见附注七、40。,见附注七、40。\n",
        encoding="utf-8-sig",
    )
    (run / "table_reconciliation_audit.csv").write_text("status\nNOT_TESTABLE\n", encoding="utf-8-sig")
    (run / "header_parser_candidates.csv").write_text("parser,status\nABSOLUTE_YEAR_CLASSIC,OK\n", encoding="utf-8-sig")
    (run / "table_capture_result.json").write_text(
        "{\"stats\":{},\"columns\":[],\"rows\":[]}", encoding="utf-8"
    )

    _rewrite_capture_excel(run)  # 修复前在此抛 EmptyDataError
    assert (run / "table_capture.xlsx").is_file()


def test_write_reconciliation_audit_tolerates_5byte_long_csv(tmp_path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    (run / "table_raw_long.csv").write_bytes(b"\xef\xbb\xbf\r\n")
    out = write_reconciliation_audit(run)
    assert out.is_file()
    assert (run / "reconciliation_summary.json").is_file()
