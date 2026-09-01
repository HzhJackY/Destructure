# INC-028：Guided Discovery 重放触发机器发现唯一键冲突

## 现象

在 v6.13 Guided UI 对太保投资组合连续执行两次阶段 A 发现，第二次在
`machine_discoveries.discovery_id` 上触发 SQLite 唯一约束。首次运行中，用户选择的三份
文件只有 2024、2025 出现在阶段 A，2023 没有失败解释。

## 根因

1. `DIRECT_PORTFOLIO_TABLES` 为同一来源物理表生成确定性的 `discovery_id`，但
   `DiscoveryRegistry.save_machine()` 对每次重放都执行无条件 `INSERT`。
2. Generic Discovery 已返回逐 Registry 的 `failures`，Guided UI 没有持久化到 session 或展示，
   因而单份 PDF 的 `NO_DIRECT_PORTFOLIO_TABLE` 被静默丢弃。
3. 工作区同时存在旧寿险子公司 `中国太保2023年报.pdf` 和更新后的上市母公司
   `中国太保集团2023年年度报告.pdf`。前者确实没有当前 Registry 所需的直接投资组合表；
   2024、2025 文件则已替换为上市母公司报告。

## 修复

- 机器发现写入改为 `ON CONFLICT(discovery_id) DO NOTHING` 后核对所有不可变字段：完全一致
  视为幂等重放；任何字段不同均以 `MACHINE_DISCOVERY_IDENTITY_CONFLICT` 失败关闭，不更新
  既有证据。
- Guided UI 收集并展示逐 PDF failure，包含文件名、公司、年份、family、strategy、扫描页数、
  OCR 标记和失败原因；Definition/PDF/口径变化时同时清理该临时状态。
- 不合并、不改名也不删除两份 2023 PDF；报告法律主体继续由来源文件和 PDF 身份区分。

## 验收

- 定向 pytest：13 passed。
- 隔离 DATA_HOME 对正确的上市母公司 2023–2025 PDF 连续发现两轮：两轮均为三年各 1 个
  occurrence、各 2 个逻辑分块；Golden 全部 MATCH、OCR 0；数据库只有 6 条机器发现。
- 旧寿险子公司 2023 报告负对照：0 candidate、0 occurrence、
  `NO_DIRECT_PORTFOLIO_TABLE`。

## 边界

未运行浏览器 E2E；未执行 Stage B、Capture、Canonical、Merge；未写生产 DATA_HOME。

## 2026-08-15 后续修复

### 再现

同一 `DPT_abfda07fce4a6469a98d` 重跑时，稳定 PDF/成员/主表页身份未变，但
`confidence`、`evidence_json` 与 `candidate_note_pages_json` 因当前 resolver 证据和候选页
排序变化而不同。此前“所有列逐字相等”的实现把合法的新机器证据快照误报为
`MACHINE_DISCOVERY_IDENTITY_CONFLICT`，直接阻断 Guided Capture。

### 修复

- 明确区分稳定候选身份与机器证据版本：PDF、公司/年度、表族/成员、源表和主表页属于
  稳定身份；置信度、候选页、bbox、状态、聚类和 evidence JSON 属于可版本化证据。
- 完全相同的重放继续返回原记录；仅证据变化时保留旧行并追加确定性
  `<base_discovery_id>__R<sha256>` 版本；稳定身份变化仍 fail-closed。
- Guided UI 使用 `save_machine()` 返回的实际版本 ID 构造 raw candidate 与 occurrence，防止
  Stage A 审核对象继续引用未持久化的 base ID。
- 不删除、不覆盖也不迁移历史 `machine_discoveries`；不修改历史 Capture 或认证链接。

### 回归边界

- 定向幂等/版本测试 4/4 通过。
- 新华保险 2025 真实 PDF 在隔离数据库完成“旧生产快照 → 当前解析 → 当前解析重放”：
  主表页仍为 43、拓扑仍为 `DIRECT_COMPOUND_TABLE`、OCR 0；旧 `0.98 / [43,45]` 证据保留，
  当前 `0.96 / [43]` 追加为 `DPT_abfda07fce4a6469a98d__R897e66d4a3f4e0ad`，第三次重放
  命中同一 revision，数据库共 2 行。
- 投资组合 Discovery/拓扑/名称单位相关回归 23/24 通过；唯一失败为既有
  `test_separate_same_page_tables_keep_two_physical_identities` 缺少 `selected_topology`，
  不经过本次 Registry/UI 写入路径。
- 生产 `metadata.db` 仅只读核查，未写入；浏览器 E2E 未运行。
