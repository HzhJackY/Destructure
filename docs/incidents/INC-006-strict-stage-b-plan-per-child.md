# INC-006 — 严格 Stage B 按子表重复生成 Capture Plan

## 症状

同一份已认证主报表下的多个 `CertifiedChildTableLink` 在严格 Stage B 流程中被持久化为多份 Capture Plan。每份计划重复包含一个伪造的 Statement Anchor，导致用户看到重复计划、重复 Anchor 审计文件和不必要的执行批次。

## 根因

`ChildCaptureExecutionService._strict_links_to_plans()` 把认证子链接的记录粒度误当成计划的执行粒度：循环内为每个 `certified_link_id` 计算独立 `plan_id`，并用 `anchor_id` 回填主表元数据。该路径没有读取持久化 `statement_occurrences`，因此也丢失了主表标题、页码、公司和报告年度。

## 修复

以 `source_pdf_id + anchor_occurrence_id + table_family + scope` 作为 family-level 计划分组身份。每组生成：

```text
1 × STATEMENT_ANCHOR
+
N × NOTE_DETAIL
```

Anchor 元数据只从持久 Statement Occurrence 读取；每一条 NOTE_DETAIL 继续保留独立的已认证目标、附注编号和页码。

## 永久回归

- 同一 Anchor 的 4 条认证子链接必须只生成 1 个 Capture Plan 和 5 个 Capture Plan Items。
- 不同 Anchor 不得被聚合。
- 中国平安 2023 既有隔离 UI 认证数据必须恢复为：合并资产负债表、PDF 145、4 条附注明细。
