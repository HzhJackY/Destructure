---
name: four-company-real-delivery
description: Execute certified four-insurer financial-investment research-data delivery from real annual-report PDFs through whole-table Capture, Canonical, Merge, lineage verification, and user XLSX.
---

# Preconditions

Read:

- `../../AI_CONTEXT.md`
- `../../AI_RULES.md`
- `../../ARCHITECTURE.md`
- `../../DATA_CONTRACTS.md`
- `../../GOLDEN_CORPUS.md`
- `../../docs/agent_startup_protocol.md`

Create `CURRENT_TASK_ANALYSIS.md` before editing.

# Use this skill when

The task involves four-company 2023–2025 financial-investment delivery, required child-table targeting, whole-table Capture, Canonical generation, company/cross-company Merge, or the user research workbook.

# Forbidden

- no `resolve_metric` final path;
- no nearest-number final values;
- no note references as amounts;
- no OCR amounts injected into certified values;
- no fabricated human adjudication;
- no forced certification;
- no reuse of invalid prior delivery files;
- no investment income or long-term equity investment in the core family without Research Definition authority.

# Required workflow

```text
Frozen inputs and external denominator
→ Main-statement certification
→ CertifiedChildTableLink
→ Whole-table Capture
→ Capture certification
→ Canonical Long
→ Company Merge
→ Four-company Research Merge
→ User Research XLSX
→ PDF-to-XLSX lineage QA
```

# Completion

Return COMPLETE only when database records, artifacts, hashes, execution logs, and lineage checks exist.

Otherwise return BLOCKED with the first failed stage.
