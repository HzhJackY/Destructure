# AXA_research Golden Corpus Governance

## Purpose

Golden assets describe independently adjudicated facts in real PDFs.

They do not describe current software output, UI behavior, generated status, or implementation internals.

## Golden asset types

### Filing Identity Golden

Canonical filename, PDF SHA256, page count, company/year/report type.

### Page Anchor Golden

Page-number system, PDF reader page, printed page, scope, statement type, modality, and OCR requirement.

### Disclosure Pattern Golden

Explicit parent, implicit member set, presentation regime, and required/forbidden structural facts.

### Member Assertion Golden

Only when independently verified: required member, accepted raw labels, forbidden family membership, and note-reference expectation.

## Annotation statuses

- `PATTERN_CANDIDATE`
- `PROVISIONAL_PATTERN`
- `HUMAN_VERIFIED_PENDING_SHA`
- `HUMAN_VERIFIED`
- `INDEPENDENTLY_ADJUDICATED`
- `CERTIFIED_GOLDEN`
- `DISPUTED`
- `RETIRED`

Only independently adjudicated or certified assertions may block a release.

## 当前期与历史变体的 Anchor 验收

当同一主报表同时列示当前期新准则成员和比较期/重述旧准则成员时，
`golden_values.yaml` 的每个 `values[]` 必须标记其 `status`。Stage-A
Anchor 验收仅把 `ACTIVE_CURRENT_PERIOD` 作为当前期必需成员；例如
`RESTATED_COMPARATIVE_PERIOD` 必须保留为可审计历史变体和后续细项
parity 证据，但不能被误报为当前期缺失项。缺少历史 status 的旧 fixture
为兼容既有认证，暂按当前期成员处理，新增 fixture 不应省略该字段。

当同一规范标签在同页存在新旧制度物理行时，Golden/Canary 必须分别核验物理行、附注、
期间状态和金额，不能只按规范 `member_id` 对齐。比较期旧成员可保留为审计与桥接候选，
但不得反向定义当前期必需成员，也不得与当前期新成员求和。

## Non-circular validation

Forbidden:

```text
current parser output
→ Golden
→ parser passes Golden
```

Allowed:

```text
current output
→ candidate
→ direct PDF inspection
→ independent adjudication
→ Golden upgrade
```

## Separation from software regressions

Real PDF facts belong in Golden.

Software behavior belongs in Defect Invariants, Synthetic Fixtures, User Journey Regression, and Incident Registry.

## Current corpus

Primary corpus:

```text
golden_corpus\v1.1.0
```

Do not edit certified facts without evidence and a change-log entry.

## Governance Registry Contract

The v1.1.0 corpus has four complementary governance artifacts:

- `filing_inventory.csv`: immutable canonical target identity only.  It is not
  a coverage report and must not contain excluded candidates.
- `filing_exclusions.csv`: non-target and retired candidates with the exclusion
  reason and migration/change-log reference.
- `golden_coverage_registry.csv`: one filing summary with all asset classes,
  assertion counts, current/comparative/restated coverage, audit provenance and
  separate `PRIMARY_ONLY` / `ALL_NOTE_TABLES` release status.
- `golden_table_segment_registry.csv`: certified logical-table and physical-
  segment facts.  It is the only registry that may state a continuation parent
  relation and its source evidence.

`PRIMARY_TABLE`, `SUPPLEMENTARY_TABLE` and `CONTINUATION_SEGMENT` are distinct
facts.  A supplementary table may share a note number or a “续” title with a
primary table, but it is not a continuation unless its physical relation was
separately adjudicated.  A missing or `NOT_AUDITED` row must remain visible as
a coverage gap; it is never a zero-value assertion or a certified absence.

## Golden Identity v1.2

`golden_identity_v1_2_<family>.yaml` 是现有独立审阅事实的稳定身份 sidecar，不替代原
Golden，也不允许读取 Capture 生成值。严格验收要求 24 个 filing-profile 均通过 v1.2
schema、来源身份、物理表身份、稳定行身份、父子图与期间值校验。

投资组合缺失的平安 2024/2025 事实必须由 canonical PDF 独立核验后补入；金融投资太保
旧 SHA fixture 在当前上市母公司 PDF 完成逐页复核前保持阻断，禁止直接迁移旧金额。
supplementary 只纳入已有 `CERTIFIED_GOLDEN` 文件；未审范围继续单列 coverage gap。

v1.2 严格验收不仅检查 sidecar 内部自洽，还必须交叉核对同目录独立事实文件。对于金融
投资，`physical_tables` 中每个 current primary member 的 `physical_page_number` 必须与
`golden_values.yaml.values[].child_table.pdf_page_number` 相同；对于投资组合，必须与
`investment_portfolio_golden.yaml.physical_assets[]` 相同。任一来源矛盾均返回
`PHYSICAL_TABLE_PAGE_SOURCE_MISMATCH` 并 fail-closed，验证器不得自动选择一方或修复 Golden。

### 投资组合父子身份审阅标记

当表内 GROUP 后仍存在同级明细或合计时，source Golden 必须通过 `parent_row_order` 明确
父项边界：整数指向同一物理表、同一 member/axis 中已审阅的 GROUP；显式 `null` 表示该行
恢复 ROOT。TOTAL、同级 GROUP 和显式 ROOT boundary 都不得继承此前 group。该标记是独立
PDF 审阅事实，仅用于确定性生成 sidecar，不得从机器 Capture 反向推断或补写。

严格比较保留 `raw_label` 作为 lineage audit，但阻断判断使用规范标签、父路径、occurrence、
row kind 和期间值。一个稳定身份连接失败只能报告一次语义身份事实；不得派生为多个虚假
数值差异。
