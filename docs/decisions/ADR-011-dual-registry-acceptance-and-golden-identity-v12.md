# ADR-011：双 Registry 验收与 Golden Identity v1.2

- 状态：ACCEPTED
- 日期：2026-08-23
- 范围：`INVESTMENT_PORTFOLIO_V2`、`FINANCIAL_INVESTMENT_V1`

## 决策

建立 `RegistryAcceptanceHarness`，统一执行 Corpus、Discovery、认证快照、Capture、
Canonical、Merge 与非浏览器 UI parity 的 fail-closed 验收。Registry Profile 只拥有
Discovery/认证前半段的分叉；Whole-table Capture 以后必须消费正式 Reducer、Canonical、
Merge 与 Research XLSX 链路。

Golden 保持事实文件向后兼容，并新增 `GOLDEN_IDENTITY_V1_2` sidecar。严格验收只接受
v1.2 sidecar，行连接键由 filing、物理表、逻辑块、分类轴、规范标签、认证父路径及
同名 occurrence 构成。Golden 不保存运行时 `source_row_id`，也不得由 Capture 反向生成。

对于金融投资主表，`financial_investment_parent` 是受限共享物理 GROUP：它可在同一物理主表、
同一 `FINANCIAL_INVESTMENT_MEMBER_SET` 下连接不同的 member family；此例外不放宽跨页、跨轴
或其他 family 的父子边。

supplementary schedule 仅在原 Golden 已标记 `CERTIFIED_GOLDEN` 时进入身份 sidecar；
`NOT_AUDITED` 必须作为 coverage gap 报告，不能包装成 primary failure 或全附注成功。

UI Lane 必须通过 FakeStreamlit 调用真实 Python UI 入口与正式 backend jobs。只有生成了
可比较的正式 Capture/Canonical/Merge 语义集合，才能写 `UI_OFFLINE_SEMANTIC_PARITY`；
静态路由测试、相同数据库副本或浏览器未启动都不能替代这一证据。

## 完成门禁

每个 Registry 独立要求 12/12 当前 PDF 身份、正式认证、Capture/Canonical/Merge、
Golden 身份和数据零差异、UI/离线语义一致。旧 PDF 哈希、待人工认证、未 ready Capture
或未运行 UI Lane 均以明确 `BLOCKED_*`/`NOT_RUN` 输出，不得降级为绿色。

## 2026-08-23 P0 补充决策

- sidecar 内部 validator 之外，Corpus Preflight 必须执行 source Golden / filing 的跨文件
  一致性校验；物理页码矛盾属于硬失败。
- Stage B 候选生成后必须调用正式 `assign_global()`。脚本内局部保存链接或 repair list 不
  产生正式全局分配语义。
- 生产修复前必须备份完整 metadata SQLite；写入只允许经过正式服务及其 repository owner。

## 2026-08-24 完整验收与 append-only 恢复补充

- Guided Discovery 重放会生成新的 append-only occurrence ID。恢复正式子表资产时，先按
  当前 Anchor ID 精确查询；无结果时才允许按 `PDF + 年度 + 口径 + 主表页 + statement type
  + family` 的物理身份查询旧 owner Anchor，且旧 Anchor 必须存在正式认证审计记录。
  禁止按标签、分数或模糊页码恢复。
- `PLAN_STRICT` 身份必须包含排序后的 `certified_target_ids`。认证资产集合变化时生成新的
  Capture Plan 版本，不能静默复用旧 plan items。
- 已正式认证但机器可选几何门禁未全通过的候选，UI 保留黄色审计提示，不再显示为新的红色
  阻断；未认证候选仍严格执行硬门禁。
- 2026-08-24 双 Registry 统一验收结果为各 12/12 PASS。投资组合统一 Offline Lane 包含
  15 个物理 Capture，并生成四个公司纵向 Merge 和一个四公司 Research-wide Merge；
  Canonical 分类轴无 `UNRESOLVED`、无跨轴身份碰撞。金融投资生产批次包含 49 个 primary
  Capture 请求，12 个批次全部终态且无失败。浏览器 E2E 明确为 `SKIPPED_BY_USER`。
