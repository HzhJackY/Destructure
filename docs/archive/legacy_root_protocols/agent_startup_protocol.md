# agent\_startup\_protocol.md \- Agent 接入与启动协议

> **强制要求**：任何新 Agent（或新 Window/Session 的 Agent）在接管 AXA\_research 项目任务后，**必须严格逐步执行**本协议。在完成 Step 5 并输出 `CURRENT_STATE_AUDIT.md` 之前，**严禁对项目中的任何代码进行修改**！

---

## 5-Step Agent Startup Workflow

### Step 1: 读取项目上下文

- **动作**：完整读取 `AI_CONTEXT.md`。  
- **目的**：理解 AXA\_research 的项目目标（保险年报结构化财务数据库）、核心数据处理链路（PDF \-\> Capture \-\> Canonical \-\> Merge \-\> XLSX）、当前版本状态（v6.11）及四大保险公司的 Disclosure Pattern。

### Step 2: 读取最高优先级红线规则

- **动作**：完整读取 `AI_RULES.md`。  
- **目的**：明确 Rule 001（禁止 Single Metric Pipeline）、Rule 002（金融投资家族边界）、Rule 003（OCR Contract）、Rule 004（禁止伪造认证）及 Rule 005（Frozen Contract）等不可违背的红线约束。

### Step 3: 读取系统架构与 Ownership

- **动作**：完整读取 `ARCHITECTURE.md` 与 `docs/ownership/module_owner_registry.md`。  
- **目的**：掌握 `src/` 下 7 大模块的输入输出契约、Owner 分工与禁止依赖关系，明确本次任务涉及模块的修改边界。

### Step 4: 读取历史架构决策与事故记录

- **动作**：读取 `docs/decisions/` 下的所有 ADR（ADR-001 \~ ADR-005）与 `docs/incidents/` 下的所有事故报告（INC-001 \~ INC-004）。  
- **目的**：避免重蹈覆辙，理解各项架构冰冻决策（Frozen Decisions）背后的血泪教训（如 INC-001 的 72 条指标误抓）。

### Step 5: 生成与输出 `CURRENT_STATE_AUDIT.md`

- **动作**：在项目根目录下生成 `CURRENT_STATE_AUDIT.md`，报告当前 Agent 对项目状态的审计理解。  
- **必须包含内容**：  
  1. **当前版本 (Current Version)**：`v6.11`  
  2. **当前目标 (Current Target)**：例如“四家公司真实数据交付”或“指定模块维护”  
  3. **不可修改规则 (Non-Modifiable Rules)**：简述 Rule 001 \- Rule 005 的要点  
  4. **相关模块与 Owner (Relevant Modules & Owners)**：列出本次任务拟修改的模块及其 Owner  
  5. **已知风险与注意事项 (Identified Risks & Notes)**：针对本次任务识别的潜在回归风险

---

## 协议约束生效声明

Step 1: AI\_CONTEXT.md

   │

   ▼

Step 2: AI\_RULES.md

   │

   ▼

Step 3: ARCHITECTURE.md & ownership/

   │

   ▼

Step 4: docs/decisions/ & docs/incidents/

   │

   ▼

Step 5: Output CURRENT\_STATE\_AUDIT.md

   │

   ▼

\[ 允许开始修改代码 / 执行开发任务 \]

未完成上述 5 步即开始编写或修改代码的 Agent 行为，将被判定为非法操作！  
