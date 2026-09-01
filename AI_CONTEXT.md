# AXA_research AI Context

## Project purpose

AXA_research converts real insurance annual-report PDFs into auditable, reviewable, certified, research-ready structured financial data.

It is not:

- an OCR demo;
- a keyword-search engine;
- a single-metric scraper;
- a report generator without database lineage;
- a system allowed to invent financial amounts.

## Formal production path

```text
Canonical PDF
→ Filing identity and Golden pattern
→ Main-statement scope/family resolution
→ Required-member contract
→ CertifiedChildTableLink
→ Whole-table Capture
→ Capture Version
→ Machine evidence + Human adjudication
→ CaptureDecisionReducer
→ Canonical Long
→ Company Merge
→ Cross-company Research Merge
→ User Research XLSX
```

No final research value may skip this path.

## Mandatory project-status acceptance

Before reporting that the project, a release, or either Registry pipeline is operational, follow:

```text
docs/current/DUAL_REGISTRY_ACCEPTANCE_RUNBOOK.md
```

Every status update must use fresh 24-cell evidence for `INVESTMENT_PORTFOLIO_V2` and
`FINANCIAL_INVESTMENT_V1` across Corpus, Discovery, Certification Snapshot, Capture, Canonical,
Merge, and FakeStreamlit UI parity. A read-only harness snapshot, historical completion card,
static UI test, or pytest alone is insufficient. Supplementary coverage and browser E2E must be
reported separately.

## Stable platform baseline

```text
v6.11
V6_11_STABILIZATION_AND_CERTIFICATION_COMPLETE
```

Frozen v6.11 capabilities include:

- persistent jobs and Logical Assets;
- unified Capture/Review/Canonical/Merge architecture;
- CaptureDecisionReducer;
- Review UI rendering must not write business state;
- Stage B unified persistent execution;
- multi-block table capture;
- terminal-boundary governance;
- optional derived totals must not block source facts;
- OCR amount isolation;
- China Life implicit-member contract;
- Golden Lite v1.1.0;
- defect invariants and synthetic fixtures.

Do not reopen these decisions without an ADR.

## Current business objective

```text
FOUR_COMPANY_RESEARCH_DATA_DELIVERY_V1
```

Target corpus:

- 中国平安 2023–2025
- 新华保险 2023–2025
- 中国太保 2023–2025
- 中国人寿 2023–2025

Target scope:

```text
CONSOLIDATED
```

Target family:

```text
FINANCIAL_INVESTMENT_STATEMENT_FAMILY
```

Final delivery requires certified main-statement families, required members, required child-table links, whole-table Capture, Canonical observations, company/cross-company Merge, PDF-to-XLSX lineage, and a user-readable workbook.

## Company disclosure patterns

### 中国平安

```text
EXPLICIT_PARENT_STANDARD
```

Expected current-classification members normally include:

- 以公允价值计量且其变动计入当期损益的金融资产 / 交易性金融资产
- 债权投资
- 其他债权投资
- 其他权益工具投资

Known regression: long labels and mismatched parent/child line-index spaces must not exclude the first member.

### 新华保险

```text
EXPLICIT_PARENT_MULTI_NOTE
```

Known features: explicit parent, multiple note targets, long labels, cross-page and terminal-boundary complexity.

### 中国太保

```text
IMAGE_DOMINANT_EXPLICIT_PARENT
```

Golden main-statement page anchors:

- 2023 PDF reader page 74
- 2024 PDF reader page 73
- 2025 PDF reader page 74

Preferred structural OCR profile:

```text
FINANCIAL_TABLE_400DPI
```

OCR may identify text and geometry but may not directly write certified amounts.

### 中国人寿

```text
IMPLICIT_MEMBER_SET_SCATTERED
```

Rules:

- `raw_parent_label = null`;
- never fabricate a raw “金融投资” parent;
- legacy/new regimes remain explicit;
- term deposits and long-term equity investments are not automatically members of the financial-investment family.

## Known invalid delivery path

Permanently forbidden:

```text
PDF
→ resolve_metric / keyword search
→ nearest numeric token
→ “resolved” rows
→ research XLSX
```

Observed failures:

- note references treated as amounts;
- wrong pages and periods;
- family-boundary violations;
- no whole-table Capture;
- no Canonical/Merge lineage.

Artifacts produced through that path must be marked invalid.

## Source-of-truth priority

1. Frozen contracts and ADRs
2. Research Definition
3. Certified Golden assertions
4. Certified machine evidence and human adjudication
5. Canonical/database lineage
6. Tests and diagnostic reports
7. Chat history

Chat history is never the final source of truth.
