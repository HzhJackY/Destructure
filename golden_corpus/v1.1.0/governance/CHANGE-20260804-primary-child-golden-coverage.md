# Change Report - 三份年报 Primary Child Golden 补齐

Date: 2026-08-04  
Change Log ID: `ACL-1.1.3-PRIMARY-GOLDEN-COVERAGE`

## Changed

- 依据 canonical PDF 直接核验并补齐中国平安 2025、中国太保 2024、中国人寿 2025 的
  `golden_values.yaml`。
- 向 `golden_table_segment_registry.csv` 登记 12 条 `PRIMARY_TABLE` 物理段，共 242 个
  金额单元；没有创建或猜测 `CONTINUATION_SEGMENT`。
- 同步 `golden_coverage_registry.csv` 的主表/主子表断言计数、期间计数和 release 状态。
  三份 filing 的 `PRIMARY_ONLY` 改为 `CLEAR`；`ALL_NOTE_TABLES` 继续保持
  `BLOCKED_PENDING_FULL_NOTE_AUDIT`，因为 supplementary/continuation 尚未全部独立审计。

## Evidence

- 中国平安 2025 canonical PDF reader p262-263，单位百万元。
- 中国太保 2024 canonical PDF reader p151-153，单位千元。
- 中国人寿 2025 canonical PDF reader p167-169，单位百万元。
- 金额与期间通过 PDF 原生文字和渲染页交叉核对；未使用 parser/Capture 当前输出反推 Golden。

## Validation

- `python golden_corpus/v1.1.0/governance/validate_golden_corpus_registry.py`
  → `GOLDEN_REGISTRY_VALID`。
- 汇总：12 canonical filings、62 physical segments、53 primary、9 supplementary、0
  certified continuation。
- 正式 DATA_HOME/数据库未修改；Streamlit 浏览器验证仍为 `NOT_RUN`。

## Rollback

按 `ACL-1.1.3-PRIMARY-GOLDEN-COVERAGE` 恢复三行 coverage、删除新增 12 条 primary
segment 记录及三份新增/更新 Golden 文件；保留本报告和验证日志。
