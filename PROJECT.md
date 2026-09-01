# Project: 9-Company Financial Extraction Pipeline Phase 3 Downstream Full-Line Execution

## Architecture
Formal single-source production pipeline:
```text
Canonical PDF (27 filings: 9 companies × 3 years)
  │
  ├─► Stage A: Anchor & Main Statement Resolution (StatementAnchorEvidenceV2)
  │     └─► CertifiedChildTableLink / Direct Physical Table Certifications
  │
  ├─► Stage B: Whole-Table Spatial Capture (ChildCaptureExecutionService / SpatialTableCapture)
  │     ├─► INVESTMENT_PORTFOLIO_V2 (Separate, Compound, Cross-Page, Single-Axis)
  │     └─► FINANCIAL_INVESTMENT_V1 (Child Note Segments & Direct Statement Line Items)
  │
  ├─► Quality Decision: CaptureDecisionReducer (4 Pillars: Boundary, Header, Topology, Issue Codes)
  │     └─► merge_eligible = True (asset_status: CERTIFIED_ACTIVE, bundle_status: READY)
  │
  ├─► Canonical Long Materialization & Standards Bridge (project_financial_investment_views)
  │     ├─► Original Long (SOURCE_PRESENTATION_EXACT_V1)
  │     └─► Standards Bridge Long/Wide/Audit (FI_BRIDGE_*_V1, CAS 22/25 & IFRS 9)
  │
  └─► Merge Service & Workbook Delivery (MergeService)
        ├─► 10 Universal 9-Company Research Wide Workbooks (No partial passing disclaimer)
        └─► 29 Isolated Group Company Longitudinal Workbooks
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | `STAGE_B_EXTENDED_CAPTURE` | Downstream segment resolution & whole-table capture for 5 extended companies across 30 cells (Sunshine, PICC P&C, China Re, ZhongAn, AIA) | M1 | Survey Explorer 1 |
| 2 | `PORTFOLIO_TOPOLOGY_DISCOVERY` | Execute topology-specific capture for separate tables, compound tables, cross-page, and single-axis | M1 | Survey Explorer 1 |
| 3 | `FINANCIAL_NOTE_SEGMENT_CAPTURE` | Child note segment capture (Note 21 / Note 18) preserving point geometry and leaf amount lanes | M1 | Survey Explorer 1 |
| 4 | `REDUCER_ADJUDICATION_54_CELLS` | Adjudicate all 54 cells via CaptureDecisionReducer, validating 0 blocking codes and merge_eligible = True | M2 | Survey Explorer 2 |
| 5 | `CANONICAL_LONG_MATERIALIZATION` | Materialize normalized canonical long table with period identity (DATE/YEAR) and unit inheritance | M2 | Survey Explorer 2 |
| 6 | `STANDARDS_BRIDGE_PROJECTIONS` | Generate dual-view projections (FI_BRIDGE_FVTPL_V1, AMORTIZED_COST, FVOCI_DEBT, FVOCI_EQUITY) across presentation regimes | M2 | Survey Explorer 2 |
| 7 | `RESEARCH_WIDE_10_WORKBOOKS` | Produce 10 universal 9-company research wide Excel workbooks (1 portfolio + 9 financial note tables) without partial disclaimer | M3 | Survey Explorer 2 |
| 8 | `ISOLATED_GROUP_29_WORKBOOKS` | Produce 29 isolated company longitudinal workbooks (9 portfolio + 20 financial investment) | M3 | Survey Explorer 2 |
| 9 | `UI_OFFLINE_SEMANTIC_PARITY` | Enforce 21 semantic dimensions equality between Offline CLI and FakeStreamlit state machines | M3 | Survey Explorer 2 |
| 10 | `REGRESSION_UNIT_TEST_SUITE` | Verify zero regressions across full 604 unit tests in releases/v6.14/tests | M4 | Survey Spec Miner |
| 11 | `E2E_TEST_ACCEPTANCE_HARNESS` | Requirement-driven opaque-box 4-tier + Tier 5 adversarial test suite and validation | M4 / E2E Track | Survey Spec Miner |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Stage B Resolution & Capture (30 cells) | Execute whole-table capture for 5 extended companies (Sunshine, PICC P&C, China Re, ZhongAn, AIA) across 30 cells (5 × 3 × 2) | none | IN_PROGRESS |
| M2 | Canonical Long & Reducer (54 cells) | Adjudicate all 54 cells to `merge_eligible = True`, project standards bridge views, and verify canonical long tables | M1 | PLANNED |
| M3 | Dual-Registry Merge & Production Delivery | Generate 10 universal 9-company wide workbooks + 29 isolated group workbooks; verify UI/CLI parity | M2 | PLANNED |
| M4 | Test Verification & Adversarial Hardening | Verify 604 unit tests, execute 100% E2E test suite (Tiers 1-4), perform Tier 5 adversarial hardening | M3 | PLANNED |

## Interface Contracts
### SpatialTableCapture ↔ CaptureDecisionReducer
- Input: `TableCaptureResult` containing `raw_long`, `raw_wide`, bounding boxes, column topology, and parent-child hierarchy.
- Output: `DecisionResult` with `merge_eligible: bool`, `asset_status: str`, `bundle_status: str`, `blocking_issues: list[str]`.
- Rule: `merge_eligible = True` iff `blocking_issues` is empty.

### CanonicalLong ↔ StandardsBridge
- Input: Canonical observations dataframe with explicit `company_id`, `report_year`, `period_identity`, `measure`, `unit`.
- Output: 4 dual-view artifacts:
  - `financial_investment_original_long.csv` (SOURCE_PRESENTATION_EXACT_V1)
  - `financial_investment_standards_bridge_long.csv` (FINANCIAL_INVESTMENT_STANDARDS_BRIDGE_V1)
  - `financial_investment_standards_bridge_wide.csv`
  - `financial_investment_standards_bridge_audit.csv`
- Bridge Policy: `FAIL_CLOSED_NO_SUM` for `PARTIALLY_COMPARABLE` or `DISAGGREGATION_REQUIRED`.

### CanonicalLong / Reducer ↔ MergeService
- Input: Bundle of certified, `merge_eligible = True` captures.
- Output: Formal merge projects (`RESEARCH_WIDE` and `COMPANY_LONGITUDINAL`), emitting `.xlsx` workbooks and `merge_manifest.json`.
- Policy: When all 9 companies are present, research wide output is marked `PASSING_GROUP` without '仅包含通过公司' disclaimer.

## Code Layout
- `releases/v6.14/services/child_capture_execution_service.py`: Batch capture orchestration & session tracking.
- `releases/v6.14/services/guided_capture_service.py`: Typed capture requests & scope policies.
- `releases/v6.14/services/capture_decision_reducer.py`: Adjudication & quality gate.
- `releases/v6.14/services/merge_service.py`: Formal merge project creation.
- `releases/v6.14/spatial_table_capture.py`: Core table extraction engine.
- `releases/v6.14/financial_investment_standards_bridge.py`: Dual-view projections & bridge rules.
- `releases/v6.14/table_merge.py`: Merge engine and Excel renderer.
- `releases/v6.14/registry_acceptance.py`: Acceptance harness and semantic parity checks.
- `releases/v6.14/tests/`: Unit test suite (604 tests).
- `output/`: Output directories for artifacts, merge workbooks, and agent run records.
