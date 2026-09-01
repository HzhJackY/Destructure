# AXA_research — Gemini Project Instructions

@./AI_CONTEXT.md
@./AI_RULES.md
@./ARCHITECTURE.md
@./DATA_CONTRACTS.md
@./GOLDEN_CORPUS.md
@./docs/agent_startup_protocol.md

Before modifying code, inspect repository state, read relevant ADRs/incidents, create `CURRENT_TASK_ANALYSIS.md`, and identify the formal owner module.

Do not introduce a duplicate production path. Use `skills/*/SKILL.md` for specialized workflows.

## Mandatory User Approval Rule (Anti-Auto-Execution)

1. **Strict Human Manual Approval Required**:
   - 出具方案或计划（Plan）后，**必须且仅能等待人类用户在聊天框中显式手打回复“Proceed”、“继续”或“执行”**后，才允许进入代码修改或生产执行阶段。
   - **禁止基于系统自动授权/自动通过机制（如 IDE Auto-Approval、Review Policy、System Message 自动通知）自动进入生产**。
   - 若收到任何系统自动通过/自动授权的通知，但没有人类用户的显式直接输入，**必须判定为未授权**，严禁擅自修改任何代码或执行生产命令，必须停留在等待用户真人回复的状态。

