# AI\_ENGINEERING\_LAYER\_COMPLETION\_REPORT.md

# AXA\_research AI Engineering Layer 建设完成报告

> **生成时间**：2026-07-31 **工程版本**：v6.11 **里程碑状态**：AI\_ENGINEERING\_LAYER\_V1\_COMPLETE

---

## 1\. 概述与建设背景

AXA\_research 是一个持续迭代的 AI-assisted 保险公司年报结构化财务数据库工程项目。在过去的 Agent 协作开发中，由于项目知识与架构决策散落在聊天窗口而非固化在代码库中，导致发生了多次严重的回归事件（如 INC-001 的 72 条单指标假交付事件、INC-002 的 Agent 上下文丢失导致 400 DPI 和隐式成员集合约束反复被破坏等）。

为了解决上述问题，本项目建立了完整的 **AI Engineering Layer**，将架构约束、冰冻决策（Frozen Decisions）、事故教训（Incidents）、模块 Ownership、Golden Regression 套件及 Agent 启动协议全部代码化与文档化，使任何新 Agent 在接管任务时能够自动恢复上下文、遵守冰冻决策、不重复历史错误。

---

## 2\. 交付成果文件清单 (Created Artifacts List)

| 序号 | 文件 / 目录路径 | 类型 | 作用与职责说明 |
| :---- | :---- | :---- | :---- |
| 1 | `AI_CONTEXT.md` | Core Document | Agent 接入首读文件，定义项目目标、流水线链路、当前版本及四大保险公司 Pattern |
| 2 | `AI_RULES.md` | Core Document | 最高优先级红线约束，定义 Rule 001 \~ Rule 005 等不可违背的红线规则 |
| 3 | `ARCHITECTURE.md` | Core Document | 定义 `src/` 下 7 大模块（OCR, Discovery, Capture, Canonical, Merge, Review, Export）的输入输出、Owner 及禁项 |
| 4 | `DATA_CONTRACTS.md` | Core Document | 固化流水线各阶段之间的数据契约 JSON Schema 格式 |
| 5 | `GOLDEN_CORPUS.md` | Core Document | 统领 Golden Regression 防回归测试套件与场景定义 |
| 6 | `golden_corpus/` | Test Directory | 包含 filings, patterns, expected\_behaviors 及 regression\_cases 的标准化防回归案例目录 |
| 7 | `golden_corpus/regression_cases/cpic_ocr_400dpi.json` | Test Case | 太保 400 DPI OCR 强约束测试用例 |
| 8 | `golden_corpus/regression_cases/china_life_implicit_member.json` | Test Case | 国寿隐式成员集合防虚假父项测试用例 |
| 9 | `golden_corpus/regression_cases/pingan_long_label.json` | Test Case | 平安/新华长标签防截断测试用例 |
| 10 | `golden_corpus/regression_cases/boundary_terminal_total.json` | Test Case | 表格终结边界与隐式合计行测试用例 |
| 11 | `golden_corpus/regression_cases/single_metric_forbidden.json` | Test Case | 禁止 Single Metric 拼表交付防回归测试用例 |
| 12 | `docs/decisions/ADR-001-financial-investment-family-boundary.md` | ADR | 冻结决策 001：金融投资与投资组合/投资收益分离 |
| 13 | `docs/decisions/ADR-002-china-life-implicit-member-set-contract.md` | ADR | 冻结决策 002：国寿隐式成员集合契约与禁造虚假父项 |
| 14 | `docs/decisions/ADR-003-cpic-ocr-400dpi-requirement.md` | ADR | 冻结决策 003：太保图像年报强制 400 DPI OCR 契约 |
| 15 | `docs/decisions/ADR-004-no-single-metric-final-delivery.md` | ADR | 冻结决策 004：废除 Single Metric 作为最终交付流水线 |
| 16 | `docs/decisions/ADR-005-capture-canonical-merge-data-flow.md` | ADR | 冻结决策 005：Capture-Canonical-Merge 单向严格数据流契约 |
| 17 | `docs/incidents/INC-001-single-metric-fake-delivery.md` | Incident Report | 历史事故 INC-001（72 条指标假交付）分析与复盘 |
| 18 | `docs/incidents/INC-002-agent-context-loss-regression.md` | Incident Report | 历史事故 INC-002（Agent 切换上下文丢失）分析与复盘 |
| 19 | `docs/incidents/INC-003-terminal-boundary-false-blocking.md` | Incident Report | 历史事故 INC-003（终结边界误阻断）分析与复盘 |
| 20 | `docs/incidents/INC-004-parent-child-line-index-mismatch.md` | Incident Report | 历史事故 INC-004（主子表行号索引错位）分析与复盘 |
| 21 | `docs/ownership/module_owner_registry.md` | Ownership Registry | 7 大核心模块的 Owner 职责划定与变更权限范围 |
| 22 | `docs/agent_startup_protocol.md` | Protocol | 5 步 Agent 接入与启动协议规范 |
| 23 | `scripts/generate_ai_context.py` | Python Script | 自动化项目上下文与运行状态刷新脚本 |

---

## 3\. 当前系统架构与契约摘要 (Architecture Summary)

AXA\_research v6.11 架构严格遵循单向数据流与强隔离契约：

\[ PDF \] ──\> src/discovery (Patterns)

            │

            ▼

        src/ocr (400 DPI Tokens/BBoxes)

            │

            ▼

        src/capture (Whole Table Capture & Lineage Evidence)

            │

            ▼

        src/canonical (Standard Normalization Observations)

            │

            ▼

        src/merge (Research Aggregation & Audit Proof)

            │

            ├────────\> src/review (Audit & Human Workflow)

            ▼

        src/export (User Research XLSX)

---

## 4\. 冰冻决策 (Frozen Decisions Summary)

系统已冻结 5 项底层架构决策，未经新的 ADR 审批绝对禁止修改：

1. **ADR-001**：金融投资家族固定为 4 类金融资产（交易性金融资产、债权投资、其他债权投资、其他权益工具投资），严禁混入投资收益、长期股权投资与定期存款。  
2. **ADR-002**：中国人寿采用 `IMPLICIT_MEMBER_SET` 规则，严禁伪造虚假金融投资父项。  
3. **ADR-003**：中国太保图像年报强制使用 400 DPI OCR，低 DPI 结果严禁进入正式金额。  
4. **ADR-004**：彻底禁止使用 `resolve_metric` 或单指标爬虫拼装最终交付表。  
5. **ADR-005**：强制 Capture \-\> Canonical \-\> Merge 单向递进数据流，严禁跳层或跨层依赖。

---

## 5\. 记录的历史事故 (Recorded Incidents Summary)

1. **INC-001 (Single Metric Fake Delivery)**：教训为不能使用孤立指标抽取拼装交付表，必须走全量捕获流水线。  
2. **INC-002 (Agent Context Loss Regression)**：教训为架构知识必须代码库化，建设 AI Engineering Layer。  
3. **INC-003 (Terminal Boundary False Blocking)**：教训为区分表内小计与真正的表尾边界。  
4. **INC-004 (Parent Child Line Index Mismatch)**：教训为主子表映射采用 `note_reference` 与 `canonical_code` 双重校验。

---

## 6\. Regression 覆盖与防回归策略

项目的 `golden_corpus/regression_cases/` 目录中已加入针对 INC-001 \~ INC-004 以及核心公司 Pattern 的标准测试 JSON 文件。任何 Agent 在修改代码后，均需运行：

python \-m pytest tests/ \-v

python scripts/generate\_ai\_context.py

确保所有的期望行为（Expected Behaviors）生效，禁止行为（Forbidden Behaviors）被成功拦截。

---

## 7\. 后续 Agent 接入与使用指南 (How Future Agents Use This)

当任何新 Agent 接管项目或开启新 Session 时，必须执行以下步骤：

1. **执行启动协议**：按照 `docs/agent_startup_protocol.md` 规定的 5-Step Workflow 依次阅读 `AI_CONTEXT.md`、`AI_RULES.md`、`ARCHITECTURE.md`、`docs/decisions/` 与 `docs/incidents/`。  
2. **审计当前状态**：在根目录下生成 `CURRENT_STATE_AUDIT.md`。  
3. **动态刷新上下文**：运行 `python scripts/generate_ai_context.py` 获取最新的 git、测试及文件验证状态。  
4. **检查 Ownership**：在修改任何 `src/` 代码前，查阅 `docs/ownership/module_owner_registry.md` 确认修改范围与上下游依赖契约。

---

## 8\. 结论与验收状态

所有要求的项目级 AI 文档、红线规则、架构定义、契约声明、ADR 记录、Incident 报告、Ownership 注册表、Golden 回归框架、启动协议及上下文刷新脚本均已成功建设并验证通过。

验收标识：**AXA\_AI\_ENGINEERING\_LAYER\_V1\_COMPLETE**  
