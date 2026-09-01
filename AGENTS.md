# AXA_research — Codex Project Instructions

Before modifying any file:

1. Read `AI_CONTEXT.md`.
2. Read `AI_RULES.md`.
3. Read `ARCHITECTURE.md`.
4. Read `DATA_CONTRACTS.md`.
5. Read `GOLDEN_CORPUS.md`.
6. Read `docs/agent_startup_protocol.md`.
7. Inspect branch, `git status`, and recent commits.
8. Read relevant ADRs and incidents.
9. Create `CURRENT_TASK_ANALYSIS.md`.

Do not edit code before the analysis exists.

Formal production path:

```text
Canonical PDF
→ Main Statement Resolution
→ CertifiedChildTableLink
→ Whole-table Capture
→ CaptureDecisionReducer
→ Canonical Long
→ Merge
→ User Research XLSX
```

Do not bypass this path. Do not create a parallel OCR, Capture, Review, Canonical, Merge, or export pipeline.

After a change:

- update the relevant ADR, incident, contract, or architecture file;
- run targeted tests and affected Golden/Canary regressions;
- run the smallest relevant real-PDF test;
- create a Change Report;
- do not claim COMPLETE from generated reports alone.

Use the relevant workflow under `skills/`.

## Workflow Rules

1. **Planning First Phase**:
   When requested to design, plan, or review a task workflow:
   - Output the plan in markdown format ONLY.
   - Do NOT execute any terminal commands or file modifications in the same turn.
   - You MUST end your response with: "Please review the plan above. Reply 'Proceed' to execute."
   - Wait for explicit user confirmation before proceeding to execution.
   - **Anti-Auto-Execution**: 必须且仅能等待人类用户在聊天中显式手打回复“Proceed”、“继续”或“执行”。禁止基于系统自动授权/自动通过机制（如 IDE Auto-Approval、Review Policy、System Message 自动通知）自动进入生产执行。遇到系统自动通过通知时必须保持等待状态。

2. **Progress Feedback for Long-Running Tasks**:
   When executing a multi-step or long-running task:
   - Break down the task into clear, trackable milestones/nodes.
   - Report task progress and status back to the user immediately after completing each milestone/node.
   - Keep progress reports concise, summarizing what was completed, key outcomes/results, and the next planned step.
