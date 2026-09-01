# AXA_research — Claude Code Instructions

@AI_CONTEXT.md
@AI_RULES.md
@ARCHITECTURE.md
@DATA_CONTRACTS.md
@GOLDEN_CORPUS.md
@docs/agent_startup_protocol.md

Before coding:

1. Inspect git status and recent commits.
2. Read relevant ADRs, incidents, and ownership rules.
3. Create `CURRENT_TASK_ANALYSIS.md`.
4. Identify the unique owner module.
5. Search for the existing implementation before proposing a new pipeline.

Never use single-metric search, nearest-number extraction, or generated summary files as the final research-data path.

Use specialized workflows under `skills/`.
