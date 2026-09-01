# v6.11 Strict Family Capture Plan 聚合修复报告

## 变更

严格子表映射适配器不再按单个 `CertifiedChildTableLink` 建计划，而是按来源 PDF、Anchor、表族和口径聚合为 family-level Capture Plan。

## 保持不变

- 每个附注明细仍以独立 Job 进入 Whole-table Capture。
- Golden、主表发现、子表定位和金额解析均未修改。
- 不会删除或改写既有 Capture、Capture Plan 或审计证据。

## 验证

- 单元/持久化/用户旅程定向回归：10 passed。
- 中国平安 2023 既有隔离 UI 认证数据只读 canary：1 Plan、1 Anchor、4 Detail；主表为合并资产负债表 PDF 145。

## 风险

已有历史重复计划保留为历史审计事实；本修复不自动归档或合并它们。后续 UI 重新执行同一认证链接会生成新的聚合计划。
