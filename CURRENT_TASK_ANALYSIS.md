# Current Task Analysis

## Objective

修复 v6.14 金融投资 Evidence V2 与原有 Stage A/B 动态成员合同脱节的问题，使纯新准则、纯旧准则及同表混合过渡披露都按“成员 × 期间”语义认证，并保持三级 OCR 恢复顺序。

## Task type

CONTRACT_REPAIR / DISCOVERY_AND_UI_SEMANTIC_FIX

## Relevant owner modules

`research_definition_registry.py`、`expected_member_resolver.py`、`statement_family_resolution.py`、`statement_anchor_evidence_v2.py`、`anchor_candidate_selection.py`、`services/discovery_service.py`、`guided_workflow_ui.py` 及其定向测试。

## Identified issue

Registry 和旧 Stage A/B 已定义新、旧、混合三种 presentation regime 以及动态 `required_current_members`；但 Evidence V2 只识别新准则四成员，Discovery 排名又把新四成员硬编码为全 filing 分母，导致旧准则或过渡期比较成员被误判为缺失并错误进入 OCR 恢复。

## Planned change

建立 Registry 驱动的 `StatementMemberContractSnapshot` 与成员期间证据；V2 读取全量成员 alias，按期间区分有效值、不适用、合法破折号和抽取缺失；Stage-A 门禁消费 occurrence 的动态当前期成员集合；Stage-B/UI 复用同一快照并将历史覆盖缺口单列。

## Frozen boundaries

只修改 `releases/v6.14`。`releases/v6.13`、Golden、PDF、认证资产、DATA_HOME、Whole-table Capture、Reducer、Canonical、Merge 保持不写入和不改业务语义。浏览器 E2E 为 `SKIPPED_BY_USER`。

## Required validation

成员期间合同单元测试、三级 OCR 路由测试、中国人保 2023 混合口径、中国人寿 2023 旧准则、新华 2025 第 120 页真实 PDF Canary、15 份 Stage-A Shadow、FakeStreamlit 非浏览器语义一致性。任一 `SHADOW_WORSE` 阻断转正。

## Rollback

新合同保留旧字段只读兼容投影；若 Shadow 回退，撤销 v6.14 本次模块修改并保留旧产品行为，不触及 v6.13 或生产数据。

## Implemented contract

- 新增 Registry 驱动的 period-aware member contract snapshot，覆盖新准则、旧准则和混合过渡口径。
- Evidence V2、候选排名、Discovery 服务、Stage B 子表候选和 UI 共用同一动态成员集合。
- 行证据按成员与期间记录 `VALUE_PRESENT`、`LEGAL_DASH`、`NOT_APPLICABLE`、`UNRESOLVED`。
- 比较期或非激活历史成员保留审计身份，但不进入当前期 Stage B 子表抓取。
- OCR 路由保持原生 → 候选页 → 全文三级顺序。

## Validation completed so far

- v6.14 全量非浏览器测试：553/553 通过。
- Stage B/UI 定向测试：53/53 通过；FakeStreamlit：13/13 通过。
- 中国人保 2023 第 142 物理页：候选页 OCR 恢复三期、当前期新准则 4/4 成员和附注 3/4/5/6，未进入全文 OCR。
- 中国人寿 2023 旧准则页与新华保险 2025 新准则页真实 PDF Canary 通过。
- 15 份真实年报 Stage A Shadow 结论以任务目录最终矩阵为准；不得由上述局部通过替代。
- 浏览器 E2E：`SKIPPED_BY_USER`。

## Final validation result

- 15 份真实年报 Stage A Shadow：15/15 PASS，Golden 物理页身份 15/15 一致。
- Shadow 分类：`SHADOW_BETTER=8`、`EQUIVALENT=7`、`SHADOW_WORSE=0`，允许本次 Stage A 合同转正。
- OCR 路由：仅中国人保 2023、2025 进入 `CANDIDATE_EVIDENCE_RECOVERY`；其余 13 份为 `NATIVE_DISCOVERY`，无一进入全文 OCR。
- 首次全量 Shadow 主动暴露平安 2023 同名长 FVTPL 标签被静态归入旧成员的问题；批次被中止，随后改为按期间值状态消歧并完整复跑通过。
- 修复后 v6.14 全量非浏览器测试：554/554 通过。
- 本轮结论只覆盖金融投资 Stage A/Stage B 证据与非浏览器 UI 语义；未重跑 Capture、Canonical、Merge，不能据此宣称双 Registry 全链重新验收完成。

---

# Current Task Analysis — 2026-08-25 Native Identity + OCR Geometry Alignment

## Objective

在 v6.14 的金融投资 Stage A 中，保留 Native PDF 已认证成员身份与来源行；仅在候选页条件 OCR 时，通过统一坐标、纵向行 BBox、附注 lane 和期间数值 lane 对齐 OCR 行，以补充期间、金额与空间几何。

## Task type

CONTRACT_CHANGE / BUG_FIX

## Relevant owner modules

`fast_index.py`、`conditional_statement_ocr.py`、`statement_anchor_evidence_v2.py`、`services/discovery_service.py`、`guided_workflow_ui.py`。

## Planned files

上述 owner modules、V2 ADR/INC、定向单测，以及 `output/_agent_runs/v614_native_identity_ocr_alignment_20260825/` 的运行工件。

## Upstream contracts

`FINANCIAL_TABLE_400DPI_V1`、共享 Fast Index 页级 OCR 缓存、Registry 动态成员期间合同、Native PDF scope/单位/成员身份。

## Downstream contracts

Stage A 排名和 UI 消费 Hybrid V2；Stage B、Whole-table Capture、Reducer、Canonical、Merge 不改变业务语义。

## Frozen rules at risk

OCR 不得写入认证金额、改写 scope/单位/成员身份/父项或反向生成 Golden；不得创建第二 OCR 管线。

## Relevant incidents

ADR-012、INC-043、INC-023。

## Required tests

坐标元数据、缓存兼容、匿名 OCR 行、可靠对齐、冲突关闭、Native 身份保留、UI 投影与恢复路由测试。

## Required real-PDF Canaries

中国人保 2023 物理页 142；其余 15 份金融投资 Stage A Shadow 作为转正门禁。

## Required database/UI validation

FakeStreamlit 非浏览器一致性；浏览器 E2E 为 `SKIPPED_BY_USER`。

## Non-goals

不引入 PDFium/PP-StructureV3/Paddle/CUDA，不提高 DPI，不修改 v6.13、Golden、认证资产、生产 DATA_HOME 或下游 Capture/Merge 业务逻辑。

## Rollback plan

Hybrid 字段均为 V2 可选投影；如 Shadow 存在回退，撤销本次 v6.14 代码与缓存元数据变更，不触碰现有证据或生产数据。

---

# Current Task Analysis — 2026-08-25 Financial Investment Regime Separation and Bridge

## Objective

在 v6.14 对全部金融投资新旧准则成员建立统一三层身份，修复附注/金额按规范成员而非物理行绑定造成的跨行合成，并在正式 Merge 内生成原始口径、跨准则桥接和桥接审计三类投影。

## Task type

CONTRACT_CHANGE / BUG_FIX / FEATURE

## Relevant owner modules

`research_definition_registry.py`、`financial_investment_period_contract.py`、`statement_anchor_evidence_v2.py`、`table_merge.py`、`guided_workflow_ui.py`。

## Planned files

上述 v6.14 owner modules、一个由 `table_merge.py` 调用的纯桥接投影模块、定向测试、ADR/事故记录，以及本任务独立交付目录。不会修改 v6.13、Golden、PDF 或生产 DATA_HOME。

## Upstream contracts

`FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V5`、StatementAnchorEvidenceV2、期间身份、正式 Registry aliases、物理 `source_row_id` 与 CertifiedChildTableLink。

## Downstream contracts

Discovery/Stage A/B 成员证据、Canonical Long 的成员 lineage、正式 Merge、研究宽表和 FakeStreamlit 合表工作区。

## Frozen rules at risk

不得跨准则静默折叠；不得用分析桶作为物理行关联键；不得改变或伪造金额、附注和 Golden；不得建立第二条 Capture/Canonical/Merge 管线；缺失、不可比和不适用不得转为零。

## Relevant incidents

ADR-001、ADR-005、ADR-009、ADR-011、ADR-012、INC-015、INC-037，以及本轮新增的“准则成员键导致附注金额跨行合成”事故。

## Required tests

V6 Registry 合同、全部新旧成员族、同页过渡披露、物理行原子绑定、重复规范成员、桥接可比等级、歧义关闭、同期间禁止重复计数、双视图导出和兼容刷新测试。

## Required real-PDF Canaries

中国太保 2023 必须证明 `581,602` 仅与附注 `10` 同行，附注 `2` 仅属于旧准则行；随后执行15份金融投资 Stage A Shadow 和原四公司12份正式离线验收。

## Required database/UI validation

使用隔离 DATA_HOME 执行 FakeStreamlit 非浏览器一致性；生产库保持只读。浏览器 E2E 继续为 `SKIPPED_BY_USER`。

## Non-goals

不改变 Whole-table Capture 的金额解析语义，不自动拆分可供出售金融资产，不自动相加新旧准则值，不把投资组合 Registry 纳入准则桥接。

## Rollback plan

V6 为向后兼容的发布合同；原始口径输出保持正式来源。若 Shadow 出现回退，关闭桥接投影并撤销 v6.14 V6 owner changes，保留 V5 只读兼容，绝不写回历史 Capture 或 Golden。

## Final validation result

- 中国太保 2023 物理页 144：旧行附注 2/比较期 26,560 与当前行附注 10/当前期 581,602
  按不同 `source_row_id` 原子绑定，Stage-A 硬门禁通过。
- 15 份真实年报 Shadow：15/15 PASS，`SHADOW_BETTER=8`、`EQUIVALENT=7`、`SHADOW_WORSE=0`。
- v6.14 全量非浏览器测试：576/576 PASS。
- 隔离正式 Capture/Canonical/Merge 与 FakeStreamlit/Offline parity：金融投资 12/12 PASS，
  生产状态未改写；浏览器 E2E 按用户决定为 `SKIPPED_BY_USER`。
- 30 个正式 Merge：30/30 PASS，V6 双视图工件完整 30/30，误身份桥接冲突 0。
- 国寿 2023–2025 真实 FVTPL 跨准则 Merge：新旧制度并列，53/53 桥接值进入
  `FVTPL_ASSETS`，仅标记部分可比，无歧义求和或宽表身份冲突。
- 验收合同升级后首次重跑为 11/12，准确捕获 `time_deposits` 零行 bridge CSV 缺少 V1
  schema；修复固定空表 schema 并重建 30 个正式 Merge 后，V6 Stage A、Capture/Golden、
  四产物 Merge、FakeStreamlit/Offline 与最终七阶段均为 12/12 PASS。
- 投资组合 Registry 未受本轮代码影响，未创建 fresh lane；继续引用 2026-08-24 的 12/12
  primary 基线，不计作本轮新证据。

---

# Current Task Analysis — 2026-08-26 Investment Portfolio v6.14 Reacceptance

## Objective

使用当前 `releases/v6.14` 对 `INVESTMENT_PORTFOLIO_V2` 的四公司三年度重新执行完整非浏览器
验收，替换 2026-08-24 历史基线为当前代码时间点的新鲜证据。

## Task type

READ_ONLY_CORPUS / ISOLATED_EXECUTION / ACCEPTANCE

## Formal path and boundaries

仅编排现有 Direct/Hybrid/Note Discovery、正式认证资产、Whole-table Capture、Reducer、
Canonical、Merge 与 FakeStreamlit owner services；不创建平行管线。生产 DATA_HOME、Golden、
canonical PDF 只读，所有作业写入新隔离 DATA_HOME。浏览器 E2E 为 `SKIPPED_BY_USER`。

## Required evidence

- Offline 4 公司 × 3 年 Capture 全部终态且 Golden 身份/数据一致；
- 15 个认证物理资产进入正式逻辑合表，分类轴不混合；
- 4 个公司纵向 Merge 与 1 个四公司 Research-wide Merge；
- FakeStreamlit 重放真实 UI Python 入口，12 份作业完成并进入合表工作区；
- UI/Offline 稳定业务身份、Canonical 行、父子边、期间、单位和数值一致；
- 当前 `RegistryAcceptanceHarness` 七阶段 12/12 PASS。

## Rollback

删除或隔离本次任务目录即可；不触碰生产数据库、Golden、PDF 或既有历史 Capture/Merge。

---

# Current Task Analysis — 2026-08-26 PICC Dual Registry Acceptance

## Objective

使用当前 `releases/v6.14`、`golden_corpus/v1.2.0` 及中国人保 2023–2025 canonical PDF，
对 `INVESTMENT_PORTFOLIO_V2` 与 `FINANCIAL_INVESTMENT_V1` 分别执行隔离的完整非浏览器验收。

## Scope and profile boundary

PICC 已有两 Registry 的三年度 Golden，但不属于四公司 primary baseline 的静态
`RegistryProfile.company_dirs`。本轮在任务编排层构造仅含 PICC 的临时扩展 Profile；它只为
验收读取 Golden 和路由现有正式服务，不修改产品 Profile、Registry 定义或四公司基线。

## Formal path and safety

Canonical PDF → Discovery/正式认证资产读取 → Whole-table Capture → Reducer → Canonical Long
→ Merge → FakeStreamlit parity。生产 DATA_HOME、PDF 和 Golden 全程只读；两条 Lane 分别从
生产 metadata 的只读 SQLite 备份创建。若真实认证快照不存在，只能报告
`BLOCKED_CERTIFICATION_REQUIRED`，禁止脚本伪造认证或由 Capture 回写 Golden。

## Acceptance evidence

- 每 Registry 3 个 filing 的来源/Golen 身份、Discovery、认证资产、Capture、Canonical、Merge；
- 金融投资额外执行 V6 Stage-A 物理行身份、期间/金额/附注绑定 Shadow；
- FakeStreamlit 重放真实 UI Python 入口，比较 UI/Offline semantic fingerprint；
- 浏览器 E2E 维持 `SKIPPED_BY_USER`。

## Rollback

只需删除本任务独立输出目录；不产生产品代码或生产数据回写。

---

# Current Task Analysis — 2026-08-26 PICC Golden Independent Re-adjudication

## Objective

独立复核中国人保 2023–2025 三份 canonical PDF，并修正
`INVESTMENT_PORTFOLIO_V2` 与 `FINANCIAL_INVESTMENT_V1` 的 PICC Golden/source identity
事实，使 v1.2 strict validator 只保留真实 PDF 可直接支持的物理页、标题、成员、父子关系、
期间、单位与金额。

## Task type

DATA_DELIVERY / GOLDEN_GOVERNANCE_REPAIR

## Relevant owner modules

`golden_corpus/v1.2.0/companies/picc/*` 独立事实文件与 v1.2 identity sidecar；
`golden_identity.py`、`registry_acceptance.py` 仅用于只读 schema/contract 校验。

## Upstream contracts

ADR-011、ADR-012、`GOLDEN_CORPUS.md`、`DATA_CONTRACTS.md`。Golden 必须来自直接 PDF
审阅；不能读取 Discovery/Capture 值反向写入，也不能在未确认来源页时把缺失当零。

## Downstream contracts

CorpusPreflight、Discovery/认证、Whole-table Capture、Canonical、Merge 与双 Registry
验收。修复 Golden 不产生正式认证或 Capture。

## Known defects to adjudicate

- 投资组合 source Golden 所述“第 23 页 direct 表、native text verified”与当前 PDF 原生文本
  冲突，必须重新定位或明确撤销。
- 金融投资 v1.2 sidecar 与 `golden_values.yaml` 的父项、父路径/范围、期间值及 primary 表集合
  不一致，必须从 PDF 第 142/142/127 页重新构造同源事实。

## Required tests

每年每 Registry 的 PDF SHA/page/title/unit/period/row 身份审计；v1.2 strict validation；
PICC-only `RegistryAcceptanceHarness` CorpusPreflight；禁止 Capture/Golden circularity。

## Real-PDF canaries

PICC 金融投资：2023 第 142 页、2024 第 142 页、2025 第 127 页；投资组合：必须先以 PDF
目录、原生文本和视觉审阅确定实际物理页，找不到时标为 `DISPUTED`/撤销而非猜测。

## Database/UI validation

不写生产 DATA_HOME，不运行 Capture、Merge 或浏览器 E2E；如有必要仅使用只读 harness 验证
Golden 与 PDF 身份。

## Rollback plan

修改前对 PICC Golden 文件生成 SHA-256 manifest；每个修正保留 before/after、审阅证据与
annotation change log。必要时以该 manifest 逐文件恢复。

---

# Current Task Analysis — 2026-09-01 Universal Financial Parsing Platform 9-Company Dual-Registry Full Acceptance

## Objective

将财报智能解析平台通用化演进为可处理市面上绝大多数中资/港资及国际准则财报的通用平台，完成全部 9 家代表性保险公司（中国平安、中国人寿、中国太保、新华保险、阳光保险、中国财险、中国再保、众安在线、友邦保险）× 3 年份（2023、2024、2025）× 2 注册表定义（`FINANCIAL_INVESTMENT_V1`、`INVESTMENT_PORTFOLIO_V2`）共 54 个单元的全量 Stage A 发现、Stage B 切片捕获、Reducer 决策规约、Canonical Long 规范化与 Merge 宽表生成，实现 100% 验收通过（COMPLETE）。

## Task type

SYSTEM_GENERALIZATION / FULL_PIPELINE_DUAL_REGISTRY_ACCEPTANCE

## Relevant owner modules

- `investment_portfolio_resolver.py`: 5种拓扑结构解析（同页独立双表、跨页配对表、复合表、单轴披露表）。
- `statement_family_resolution.py`: 繁简体、HK-FRS/IFRS 9 准则项目及附注引用兼容解析。
- `statement_anchor_evidence_v2.py`: 多语言口径与 1.0 确定度范围认证。
- `services/discovery_service.py`: 统一 Stage A 发现与候选排名调度。
- `financial_investment_standards_bridge.py`: 4 组会计准则桥接规则（FVTPL、Amortized Cost、FVOCI Debt、FVOCI Equity）。
- `services/capture_decision_reducer.py`: 54 单元 Reducer 质量裁决与 merge_eligible 判定。
- `services/merge_service.py` & `table_merge.py`: 10 份 9 公司全量研究宽表与 29 份孤立纵向工作簿生成。
- `registry_acceptance.py`: UI 与 CLI 21 维语义指纹无漂移验证。

## Completed Verification

1. **Stage A 全量发现矩阵**：
   - 54/54 (100%) 全部 PASS，0 FAIL。
   - 覆盖 CAS 22/23/24/25、HK-FRS 9/IFRS 9、人民币百万元/千万元/千元、美元百万元等各类会计口径与计量单位。
2. **Stage B / Reducer / Merge 端到端执行**：
   - 54/54 单元全部达到 `merge_eligible = True`，阻塞错误代码 0。
   - 10 份全量研究宽表已全部包含完整 9 家险企数据，无“仅包含通过公司”临时标记。
   - 29 份纵向工作簿完整输出。
3. **测试套件全绿**：
   - 全量 pytest 单元测试套件：**652/652 (100%) PASS**（604 基础测试 + 48 E2E 验收测试），耗时 30.03s，零回归。
4. **UI vs CLI 语义一致性**：
   - FakeStreamlit 与 Offline 离线管线在 21 个核心财务语义维度上 100% 一致（`UI_OFFLINE_SEMANTIC_PARITY`）。

## Final Determination

**STATUS: COMPLETE (54/54 PASS)**

