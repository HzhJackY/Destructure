# Incident Report INC-009: memo-only 表块空 wide CSV 使抓取 job FAILED

## 1. 事发现象 (Symptom)

GUIDED_497d75c577d7 批次（中国太保 2023，10:21）第 4 条
`中国太保2023年报__其他权益工具投资__20260804T102125_876414` 状态
`FAILED`：jobs.error_type=`EmptyDataError`、
error_message=`No columns to parse from file`；父运行
`capture_quality_status=UNASSESSED`、`merge_blockers=[PENDING_CAPTURE_COMPLETION]`。

## 2. 根本原因分析 (Root Causes)

- 附注七-13 其他权益工具投资页含 3 个表块：主表、成本/公允价值变动明细（b2）、
  纯备忘行块（b3，行内容“见附注七、40。”，0 个数值单元格）。
- b3 无金额列 → `capture_to_wide_df` 得到空 DataFrame →
  `to_csv(encoding="utf-8-sig")` 写出 5 字节 BOM+CRLF 文件。
- `capture_library._rewrite_capture_excel` 对
  `table_raw_wide.csv` 仅判断存在（5 字节存在）便 `pd.read_csv` →
  pandas 抛 `EmptyDataError` → `_create_legacy` 抛错 → orchestrator 标记
  job FAILED → 整条抓取失败，父运行停留在 UNASSESSED。

## 3. 正式修复

- `_read_csv_optional`：缺失或 EmptyDataError（空/BOM-only 文件）统一返回空 DataFrame；
  `_rewrite_capture_excel` 全部 8 个 CSV 读取改用它。
- `write_reconciliation_audit`：空/缺失长表同样防护并补齐空摘要 JSON。
- 不改动 reducer 门禁、不改动正式 Capture 数据。

## 4. 验证结论 (Verification Results)

- 回归 5/5（缺失/5 字节/正常 CSV、_rewrite_capture_excel、reconciliation 摘要）。
- 失败任务重放成功：parent+b2+b3 三个表块全部初始化完成，不再抛错。
- 相关既有回归 65 passed / 2 skipped。

## 5. 后续注意

- 其他包含 memo-only 表块的附注（跨公司）此前也可能受同样影响，修复后自动兼容。
