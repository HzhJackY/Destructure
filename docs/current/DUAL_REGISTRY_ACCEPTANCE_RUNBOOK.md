# 双 Registry 项目状态验收 Runbook

> 状态：项目状态更新的唯一标准验收合同  
> 生效版本：`releases/v6.14`  
> Registry：`INVESTMENT_PORTFOLIO_V2`、`FINANCIAL_INVESTMENT_V1`  
> 基准语料：4 家上市保险公司 × 2023–2025 年，共 24 个 filing-profile  
> 决策依据：ADR-011、ADR-013 及 2026-08-26 V6 验收补充

## 1. 强制使用规则

以后凡是更新项目状态、宣称版本可用、报告管线修复完成或判断系统能否正常运作，都必须按
本 Runbook 取得新证据。不得仅凭单元测试、旧完成卡、静态 UI 测试、历史 Capture 或只读
数据库快照宣称系统当前正常。

状态汇报至少写明：

- 被测 release、代码时间点和 DATA_HOME 类型（生产或隔离克隆）；
- 两个 Registry 各自的 12 单元结果；
- 七阶段矩阵及所有 `FAIL/BLOCKED/NOT_RUN`；
- Golden/PDF 身份与数据差异；
- Offline/UI semantic parity；
- supplementary coverage 和浏览器 E2E 边界；
- pytest 范围及通过数；
- 生产写入、备份和数据库完整性状态。

## 2. 唯一正式业务链路

```text
Canonical PDF
→ Main Statement Resolution / Direct Portfolio Resolution
→ CertifiedChildTableLink 或 Direct Physical Table Certification
→ Whole-table Capture
→ CaptureDecisionReducer
→ Canonical Long
→ Merge
→ User Research XLSX
```

验收系统只能编排和读取这条正式链路，不得建立平行 OCR、Capture、Canonical、Merge 或导出
实现，也不得用 Golden 反向生成或覆盖机器证据。

前半段按 Registry 分叉：

- `INVESTMENT_PORTFOLIO_V2`：直接披露定位、五种拓扑、物理资产与分类轴、Direct/Hybrid/Note
  路由；不同分类轴保持独立身份。
- `FINANCIAL_INVESTMENT_V1`：合并资产负债表 Anchor、成员集合、正式
  `CertifiedChildTableLink`、primary/supplementary 范围。

从 Whole-table Capture 开始，两类 Registry 必须共用 Reducer、Canonical、Merge 和 Research
XLSX owner services。

## 3. 七个强制验收阶段

| 阶段 | 核验内容 | 典型失败状态 |
|---|---|---|
| `CorpusPreflight` | 当前 PDF SHA/page、Golden Identity v1.2、filing/source Golden 跨文件一致性 | `FAIL` |
| `DiscoveryAcceptance` | 正确页、口径、拓扑/成员集合及正式 Anchor；金融投资还必须通过 V6 物理行身份与行内附注/期间/金额绑定 Shadow | `BLOCKED_DISCOVERY_OR_ANCHOR_CERTIFICATION_REQUIRED` / `NOT_RUN_FINANCIAL_V6_EVIDENCE_REQUIRED` |
| `CertificationSnapshotAcceptance` | 当前 PDF 上的正式认证资产完整且无跨 Registry 污染 | `BLOCKED_CERTIFICATION_REQUIRED` |
| `CaptureAcceptance` | Whole-table Capture 完成、身份唯一、父子图合法、Golden 身份和数据零差异 | `BLOCKED_CAPTURE_*` / `FAIL` |
| `CanonicalAcceptance` | Canonical Long 可用，期间、单位、量度、lineage 和父子投影完整 | `NOT_RUN` / `FAIL` |
| `MergeAcceptance` | 公司三年纵向与四公司研究宽表正式生成；member/axis 不混合；金融投资原始口径、桥接 long/wide、审计四产物满足 V6 fail-closed 合同 | `NOT_RUN` / `FINANCIAL_V6_DUAL_VIEW_MERGE_CONTRACT_FAIL` |
| `UiParityAcceptance` | FakeStreamlit 真实 UI Python 入口与 Offline Lane 的稳定业务语义一致；金融投资必须比较列报成员、列报制度、V6 合同和桥接 memberships | `NOT_RUN` / `UI_OFFLINE_FINANCIAL_V6_IDENTITY_NOT_COMPARED` / `FAIL` |

任何一个阶段不是 `PASS`，对应 filing-profile 都不能标记 `COMPLETE`。

## 4. 标准执行顺序

### 4.1 建立本次验收任务目录

```text
output/_agent_runs/<acceptance_run_id>/
```

必须写入 `run_stdout.txt`、`run_stderr.txt`，结束时生成：

- 24 单元验收矩阵；
- Golden Identity 审计；
- Offline/UI parity 报告；
- fail-closed 注入矩阵；
- Change Report；
- `task_completion_card.md`；
- `terminal_summary.json`；
- `final_qa.csv`。

### 4.2 Corpus 与生产前置检查

1. 确认 24 个 filing-profile 均存在 `GOLDEN_IDENTITY_V1_2` sidecar。
2. 校验 canonical PDF 的完整 SHA-256、页数、公司、法人主体、年度和口径。
3. 校验物理表身份、分类轴/member table、稳定 `golden_row_id`、父项路径、occurrence 和期间值。
4. Golden 只能来自独立 PDF 审阅；机器 Capture 不得补值或回写 Golden。
5. 若将写生产 DATA_HOME，先用 SQLite backup API 建立物理备份，并对源库及备份库执行
   `PRAGMA integrity_check`。

### 4.3 Fresh Offline Lane

- 从生产 metadata 建立隔离 DATA_HOME 克隆；生产 PDF/Golden 只读。
- 调用正式 backend service graph，为两个 Registry 各执行 12 份年报。
- 投资组合要求 15 个已认证物理资产 Capture，并按正式逻辑生成 4 个公司纵向 Merge 和
  1 个四公司 Research-wide Merge。
- 金融投资 primary 要求 49 个已认证子表 Capture；不同 member table 不得混合。
- 金融投资过渡期必须按 `source_row_id` 保留新旧准则物理 occurrence；验收不得把
  `member_table` 当物理行连接键，也不得将同期间多个来源求和。
- 比较必须通过稳定业务身份连接，禁止按行位置或运行时 `source_row_id` 直接连接 Golden。

当前已验证的编排参考位于：

```text
output/_agent_runs/dual_registry_completion_20260823/
  run_portfolio_offline_acceptance_lane.py
  create_portfolio_formal_merges.py
  run_financial_offline_acceptance_lane.py
```

这些脚本是正式 owner services 的编排适配器，不是第二条业务管线。若脚本迁入稳定工具目录，
必须同步更新本 Runbook。

### 4.4 FakeStreamlit UI Lane

- 使用新的隔离 DATA_HOME 克隆。
- 回放真实 `guided_workflow_ui.py` Python 入口并提交真实 backend jobs。
- 覆盖 Registry 选择、Stage A/B 分叉、Direct/Hybrid/Note 路由、作业创建、失败重试及进入
  合表工作区。
- 不启动浏览器；不得把该证据称为浏览器 E2E。

当前已验证参考：

```text
output/_agent_runs/dual_registry_completion_20260823/run_fake_streamlit_ui_lane.py
```

### 4.5 UI/Offline 语义比较

允许批次 ID、Capture ID、时间戳和运行目录不同；以下内容必须一致：

- filing、物理表、member table 和 classification axis；
- 金融投资 `presentation_member_id`、`presentation_regime`、
  `member_contract_version` 与 `analysis_bridge_groups`；
- Canonical 行集合、稳定 `semantic_row_key`；
- 父子边与 row kind；
- 期间身份、measure、unit 和 value；
- Merge 分组与审核状态。

当前已验证参考：

```text
output/_agent_runs/dual_registry_completion_20260823/run_ui_offline_semantic_parity.py
```

### 4.6 只读最终评价

`RegistryAcceptanceHarness` 是结果评价器，不会自行创建 fresh Discovery、Capture、Merge 或 UI
证据。以下命令只能读取指定 metadata snapshot，不能单独证明 fresh 全链成功：

```powershell
python releases/v6.14/tools/run_dual_registry_acceptance.py `
  --metadata-db <LANE_DATA_HOME>\metadata.db `
  --corpus-root golden_corpus/v1.2.0 `
  --research-batch-id <THIS_RUN_RESEARCH_BATCH_ID> `
  --formal-merge-audit <THIS_RUN_FORMAL_MERGE_AUDIT.csv> `
  --financial-v6-shadow <THIS_RUN_V6_SHADOW.csv> `
  --ui-parity-matrix <THIS_RUN_UI_PARITY.csv> `
  --output-dir output/_agent_runs/<acceptance_run_id>/snapshot
```

若没有本次运行的 research batch、正式 Merge 和 UI parity，必须输出 `NOT_RUN/BLOCKED`，不能
借用其他 lane 或历史成功状态。

### 4.7 失败注入与测试

至少覆盖：Golden 缺身份、错误 PDF 哈希、重复行身份、悬空父项、跨轴父边、跨 Registry、
错误成员族、数值漏值、层级环、认证快照缺失、ROI 证据缺失和跨 PDF 合表污染。

随后运行受影响测试与完整 pytest。浏览器 E2E 默认按用户决定记为 `SKIPPED_BY_USER`；只有
用户明确要求且真实启动浏览器后，才能改变该状态。

## 5. 完成判定

两个 Registry 必须独立报告，不能互相替代：

- `COMPLETE`：12/12 当前 PDF 身份正确，正式认证存在，Capture/Canonical/Merge 成功，
  Golden 身份和数据差异为零，UI/Offline 语义一致。
- `BLOCKED_*`：缺 PDF、Golden、Anchor、认证资产或人工决定。
- `FAIL`：身份、数据、父子图、期间、单位、分类轴/member 或 Merge 结果不一致。
- `NOT_RUN`：阶段没有产生本次运行证据。
- `COVERAGE_GAP`：primary 可以完成，但 supplementary 或 all-note 范围未完成；不得包装为
  全附注覆盖。

项目状态更新只有在 24 个 primary 单元的七阶段全部 `PASS` 时，才能写
`PRIMARY_SCOPE_COMPLETE`。若存在 supplementary gap，最终状态应写成：

```text
COMPLETE_PRIMARY_SCOPE_WITH_SUPPLEMENTARY_COVERAGE_GAP
```

## 6. 生产与 append-only 安全合同

- 生产写入必须先备份，只允许通过正式 service/repository owner 追加，不直接执行 SQL 修补。
- Discovery 重放产生新 occurrence ID 时，先按当前 Anchor ID 恢复链接；无结果时只允许通过
  正式认证审计支持的完整物理身份恢复旧链接，禁止标签或分数模糊匹配。
- `PLAN_STRICT` 必须包含排序后的 `certified_target_ids`；认证资产集合变化必须生成新 plan。
- 已正式认证 Anchor 的可选机器几何门禁失败只显示审计 WARNING；未认证候选仍 fail-closed。
- 原 DATA_HOME、PDF、Golden 和历史作业保持可追溯，不覆盖旧 Capture。

## 7. 当前认证基线（2026-08-26）

- `INVESTMENT_PORTFOLIO_V2`：12/12 primary PASS；15 个物理 Capture；5 个正式 Merge。
- `FINANCIAL_INVESTMENT_V1`：V6 Stage A 物理身份/行内绑定 12/12 PASS；隔离正式
  Capture/Golden 12/12 PASS；正式双视图 Merge 30/30 PASS。
- Golden Identity v1.2：24/24 PASS。
- 金融投资 V6 UI/Offline semantic parity：12/12 PASS。
- 投资组合已于 2026-08-26 使用当前 v6.14 重新执行：Offline 12/12、15 个物理
  Capture、正式 Merge 5/5、FakeStreamlit 12/12、UI/Offline semantic parity 12/12、
  最终七阶段 12/12 PASS。
- fail-closed 注入：12/12 PASS。
- pytest：以对应完成卡记录的本次完整非浏览器套件为准；不得沿用旧通过数。
- supplementary：6 份 filing、14 张 `CERTIFIED_GOLDEN` 表未纳入 primary lane；all-note
  release 仅 1/12 CLEAR，状态为 `COVERAGE_GAP`。

本轮金融投资参考证据：

```text
output/_agent_runs/v614_financial_regime_member_bridge_20260825/
  run_v6_acceptance_rerun.py
  financial_v6_acceptance_shadow.csv
  financial_v6_ui_offline_parity.csv
  financial_v6_merge_acceptance.json
  financial_v6_reacceptance_matrix.json
```
- 浏览器 E2E：`SKIPPED_BY_USER`。

本轮投资组合参考证据：

```text
output/_agent_runs/v614_portfolio_reacceptance_20260826/
  portfolio_v614_offline_execution_matrix.csv
  portfolio_formal_merge_audit.csv
  portfolio_v614_ui_execution_audit.csv
  portfolio_v614_ui_offline_parity_matrix.csv
  portfolio_v614_ui_offline_parity_acceptance_matrix.json
  task_completion_card.md
  final_qa.csv
```

基准证据：

```text
output/_agent_runs/dual_registry_completion_20260823/
  acceptance_matrix_24.csv
  golden_identity_migration_audit.csv
  dual_registry_unified_parity_20260824_summary.json
  failure_injection_matrix.csv
  final_qa.csv
  task_completion_card.md
  terminal_summary.json
```

## 8. 状态更新模板

```text
被测版本：
验收 run ID：
DATA_HOME：生产 / 隔离克隆
投资组合：x/12 PASS
金融投资 primary：x/12 PASS
Golden Identity：x/24 PASS
UI/Offline parity：x/24 PASS
正式 Merge：
失败注入：
pytest：
Supplementary coverage：
浏览器 E2E：
生产备份与 integrity：
最终状态：COMPLETE / BLOCKED_* / FAIL / NOT_RUN / COVERAGE_GAP
关键证据路径：
```

任何将 `NOT_RUN`、静态检查、历史证据或 coverage gap 改写成绿色成功的状态报告，均违反本
Runbook。
