# Agent Startup and Completion Protocol

## Startup gate

Before editing code, every Agent must:

1. Read project entry instructions.
2. Read `AI_CONTEXT.md`, `AI_RULES.md`, `ARCHITECTURE.md`, `DATA_CONTRACTS.md`, and `GOLDEN_CORPUS.md`.
3. Inspect branch, git status, recent commits, current release, and relevant evidence directories.
4. Read relevant ADRs and incidents.
5. Identify the owner module.
6. Search for existing implementation before designing anything new.
7. Create `CURRENT_TASK_ANALYSIS.md`.

## Required task analysis template

```markdown
# Current Task Analysis

## Objective

## Task type
BUG_FIX / CONTRACT_CHANGE / FEATURE / REFACTOR / DATA_DELIVERY / QA

## Relevant owner modules

## Planned files

## Upstream contracts

## Downstream contracts

## Frozen rules at risk

## Relevant incidents

## Required tests

## Required real-PDF Canaries

## Required database/UI validation

## Non-goals

## Rollback plan
```

No code modification before this document exists.

## Change categories

### Bug fix

Requires an incident update, regression test, affected real-PDF Canary, and Change Report.

### Contract change

Requires an ADR, schema/contract update, migration/backward-compatibility plan, and full affected regression suite.

### Feature

Requires architecture/context updates, owner assignment, unique-path analysis, and evidence package.

### Refactor

Requires proof of unchanged behavior through tests and affected Golden/Canary cases.

## Completion gate

Before claiming completion:

1. List modified files.
2. List database migrations.
3. List artifacts generated.
4. Report test layers separately.
5. Report real-PDF execution separately.
6. Report UI/restart execution separately.
7. Report lineage validation separately.
8. Update project knowledge.
9. Produce a Change Report.
10. State unresolved risks.

Generated reports, row counts, or status strings alone do not prove completion.
