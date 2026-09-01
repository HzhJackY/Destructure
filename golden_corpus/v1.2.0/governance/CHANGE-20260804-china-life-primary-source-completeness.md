# Change Report - 中国人寿主表 SOURCE Golden 完整性

Date: 2026-08-04
Change Log ID: `ACL-1.1.8-CHINA-LIFE-PRIMARY-SOURCE-COMPLETENESS`

## Changed

- 补齐中国人寿 2023“持有至到期投资”2022 年摊余成本/公允价值两列，共 10 个 SOURCE 金额槽。
- 补齐中国人寿 2024 四张主表分类明细后的第二个真实“合计”，共 4 个 SOURCE 金额槽。
- 补齐中国人寿 2025 四张主表两期间的第二个真实“合计”，共 8 个 SOURCE 金额槽。
- 同步 coverage、segment registry、annotation change log 与三份 filing evidence notes；重复“合计”按物理行序保留，没有折叠为同一行。

## Evidence

- 三份 canonical PDF 的 SHA256 与 filing identity 一致。
- PDF reader p177、p185-p187、p167-p169 的原生文字、词坐标和整页 PNG 逐项核验。
- 22 个金额均由 PDF 独立核验后写入 Golden，未从 Capture、Canonical 或 Merge 输出反推。
- 页面证据保存于 `evidence/page_crops/china_life_2023_p177_full.png`、`china_life_2024_p185_full.png` 至 `p187_full.png`、`china_life_2025_p167_full.png` 至 `p169_full.png`。

## Validation

- 官方 Golden registry validator：`GOLDEN_REGISTRY_VALID`；12 filings、53 primary、14 supplementary、0 certified continuation。
- 最终主表 parity：49/49 tables、883/883 Golden cells、fail=0、missing=0、SOURCE unasserted=0。
- 另外 24 个非 SOURCE 单元格按 runtime `row_order` 单独保留 lineage：18 个 `DERIVED_REJECTED_NON_BLOCKING`（9 行）与 6 个 `SUPPRESSED_BY_EXPLICIT_TOTAL`（3 行）；没有排除包含它们的整个 asset。

## Release State

- `PRIMARY_ONLY` 的 Golden SOURCE 断言完整性为 CLEAR。
- 本变更不改变任何 filing 的 `ALL_NOTE_TABLES` 审计状态，也不把未审计 continuation 伪造为不存在。
- Golden parity 不等于实际 Merge 完整；Canonical/Merge 对 mixed root/derived assets 的 source-cell 纳入仍由独立生产 canary 决定。

## Rollback

删除本次新增的 22 个 Golden 槽，恢复三条 coverage 与九条 segment registry 计数和 change-log ID，并移除七张新增整页证据图；保留本报告与独立 PDF 证据供审计。
