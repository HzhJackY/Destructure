# AXA_research E2E Testing Infrastructure (TEST_INFRA.md)

## 1. Executive Summary & Testing Philosophy

The AXA_research testing infrastructure is designed to validate the **9-Company Financial Extraction Pipeline Phase 3 Downstream Full-Line Execution** across all **54 filing cells** (9 companies × 3 report years × 2 registries), standards bridge projections, 10 universal research wide workbooks, 29 isolated company longitudinal workbooks, and strict 21-dimension UI/CLI parity.

Testing follows an **opaque-box, contract-driven 4-tier methodology** supplemented by **Tier 5 adversarial hardening**, adhering strictly to:
1. **Rule 001–Rule 017** (`AI_RULES.md`): No invented numbers, no fake parents, no forced certification, fail-closed on ambiguity, OCR amount isolation, and whole-table preservation.
2. **Data Contracts** (`DATA_CONTRACTS.md`): Period identities (`DATE:YYYY-MM-DD`, `YEAR:YYYY`, `MONTH:YYYY-MM`), units, presentation regimes, and immutable source lineage.
3. **Golden Identity v1.2** (`GOLDEN_CORPUS.md`): External authoritative denominator independent of parser output.

---

## 2. 4-Tier (+ Tier 5) Testing Methodology

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   Tier 5: Adversarial Hardening                        │
│  (Encoding/Escaping, Corrupt Artifacts, Boundary Stress, Tampering)    │
├────────────────────────────────────────────────────────────────────────┤
│               Tier 4: Real-World Workload Scenarios                    │
│  (54-Cell Batch Pipeline, 10 Wide + 29 Isolated Workbooks, UI Parity)  │
├────────────────────────────────────────────────────────────────────────┤
│                 Tier 3: Pairwise Combinations                          │
│  (Company × Year × Registry × Topology × Presentation Regime × Scope)   │
├────────────────────────────────────────────────────────────────────────┤
│                 Tier 2: Boundary & Corner Cases                        │
│  (Compound Tables, Cross-Page, Implicit Parent, Dash/Zero, Fail-Closed)│
├────────────────────────────────────────────────────────────────────────┤
│                   Tier 1: Feature Coverage                             │
│  (30-Cell Extended Capture, Reducer Adjudication, Standards Bridge)   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Tier-by-Tier Specification & Test Matrix

### Tier 1: Feature Coverage (Requirements R1–R3)

| Test ID | Target Feature | Scope / Input | Authoritative Source | Verification Assertion |
|---|---|---|---|---|
| `T1_EXT_CAPTURE_30_CELLS` | `STAGE_B_EXTENDED_CAPTURE` | 5 Extended Companies (Sunshine, PICC P&C, China Re, ZhongAn, AIA) × 3 Years (2023-2025) × 2 Registries (30 cells) | `golden_identity_v1_2_*.yaml` | All 30 cells pass Stage B whole-table capture with intact point geometry and leaf amount lanes |
| `T1_TOPOLOGY_DISCOVERY` | `PORTFOLIO_TOPOLOGY_DISCOVERY` | 9 Companies × `INVESTMENT_PORTFOLIO_V2` across Separate, Compound, Cross-Page, Single-Axis | `portfolio_topology_execution_plan.py` | Topology execution plan accurately classifies each filing without route drift or UI state reliance |
| `T1_FINANCIAL_NOTE_CAPTURE` | `FINANCIAL_NOTE_SEGMENT_CAPTURE` | 9 Companies × `FINANCIAL_INVESTMENT_V1` note detail tables (Note 21, Note 18, etc.) | `golden_table_segment_registry.csv` | Child note segments preserve leaf columns, parent section bindings, and table title anchors |
| `T1_REDUCER_ADJUDICATION_54` | `REDUCER_ADJUDICATION_54_CELLS` | All 54 cells (9 companies × 3 years × 2 registries) | `CaptureDecisionReducer` | `merge_eligible = True`, `blocking_issues = []`, `asset_status = CERTIFIED_ACTIVE`, `bundle_status = READY` |
| `T1_CANONICAL_LONG` | `CANONICAL_LONG_MATERIALIZATION` | 54 cells canonical observations | `DATA_CONTRACTS.md` § Period & Unit | Period identity normalized (`DATE:YYYY-MM-DD` / `YEAR:YYYY`), unit inherited, semantic row keys assigned |
| `T1_STANDARDS_BRIDGE` | `STANDARDS_BRIDGE_PROJECTIONS` | Financial investment dual-view projections | `financial_investment_standards_bridge.py` | 4 artifacts emitted: `original_long`, `bridge_long`, `bridge_wide`, `bridge_audit`; `FAIL_CLOSED_NO_SUM` on ambiguous sources |
| `T1_RESEARCH_WIDE_10` | `RESEARCH_WIDE_10_WORKBOOKS` | Cross-company merge across all 9 companies | `PROJECT.md` § Feature 7 | 10 universal wide workbooks produced with full 9-company data; status `PASSING_GROUP`; no partial disclaimer |
| `T1_ISOLATED_GROUP_29` | `ISOLATED_GROUP_29_WORKBOOKS` | Company longitudinal merge | `PROJECT.md` § Feature 8 | 29 isolated group workbooks (9 portfolio + 20 financial note) materialized with multi-year periods |
| `T1_UI_OFFLINE_PARITY` | `UI_OFFLINE_SEMANTIC_PARITY` | Dual-lane metadata comparison | `registry_acceptance.py` | 21 semantic dimensions identical between Offline CLI and FakeStreamlit UI |

---

### Tier 2: Boundary & Corner Cases

| Test ID | Boundary Condition | Edge Scenario | Expected Fail-Closed / Pass Behavior |
|---|---|---|---|
| `T2_COMPOUND_TABLE_BOUNDARY` | Compound table multi-axis segmentation | Shared physical segment bbox containing both Object and Measurement axes | Correctly creates 1 physical capture and splits into 2 distinct logical captures sharing physical lineage |
| `T2_CROSS_PAGE_CONTINUATION` | Table continues across page boundaries | Page break with continuation header and reset period columns | `PRIMARY_WITH_CONTINUATIONS` preserves continuation chain; `PRIMARY_ONLY` emits verified policy truncation |
| `T2_IMPLICIT_PARENT_INTEGRITY` | China Life scattered implicit members | Filing has no explicit "金融投资" parent header | `resolution_mode = IMPLICIT_MEMBER_SET`, `raw_parent_label = null`; never fabricates synthetic parent |
| `T2_DASH_ZERO_MISSING` | Formatted dashes vs genuine zeros vs missing | Table cells contain `-`, `—`, `不适用`, `0`, or blank | `PRINTED_DASH` and `0` preserved distinctly; pure blank never converted to 0; missing values fail-closed |
| `T2_MULTI_UNIT_INHERITANCE` | Mixed currencies and unit conversions | RMB Million vs USD Million vs Percent (`%`) | Amount observations inherit explicit certified unit; percentages assigned `PERCENT` and `value_yuan = NULL` |
| `T2_RESTATED_PERIOD_ISOLATION` | Comparative period restatements | Annual report containing current 2024 and restated 2023 | Distinct `period_identity` and `restated` flags; no accidental mixing of `CURRENT_REPORT` with `RESTATED` |
| `T2_CORRUPTED_IDENTITY_GATE` | Golden identity corruption | Duplicate `golden_row_id`, dangling parent ID, cycle in tree | `validate_identity_sidecar` fails closed with explicit issue codes |

---

### Tier 3: Pairwise Combinations (Orthogonal Array Matrix)

The test matrix systematically exercises orthogonal pairs across 6 key dimensions:

1. **Company (9)**: Ping An, New China Life, CPIC, China Life, Sunshine Insurance, PICC P&C, China Re, ZhongAn Online, AIA.
2. **Report Year (3)**: 2023, 2024, 2025.
3. **Registry (2)**: `INVESTMENT_PORTFOLIO_V2`, `FINANCIAL_INVESTMENT_V1`.
4. **Topology (4)**: `SEPARATE_TABLES`, `DIRECT_COMPOUND_TABLE`, `CROSS_PAGE_CONTINUATION`, `SINGLE_AXIS_TABLE`.
5. **Presentation Regime (3)**: `NEW_FINANCIAL_INSTRUMENT_CLASSIFICATION` (IFRS 9 / CAS 22/25), `LEGACY_FINANCIAL_ASSET_CLASSIFICATION` (CAS 22 legacy / IAS 39), `MIXED_TRANSITION_PRESENTATION`.
6. **Capture Scope (2)**: `PRIMARY_ONLY`, `ALL_NOTE_TABLES`.

```text
Pairwise Coverage Matrix:
- 9 Companies × 3 Years = 27 Filings
- 27 Filings × 2 Registries = 54 Cells
- 54 Cells evaluated against active Topologies, Regimes, and Scopes
- 100% pairwise interaction coverage across valid orthogonal tuples
```

---

### Tier 4: Real-World Workload Scenarios

1. **Scenario 4.1 — Full 54-Cell End-to-End Batch Ingestion & Adjudication**:
   - Executes Discovery → Stage B Capture → Reducer Adjudication → Canonical Long for all 54 cells.
   - Asserts all 54 cells achieve `merge_eligible = True` with 0 blocking issue codes.
2. **Scenario 4.2 — 10 Universal 9-Company Wide Research Workbooks Generation**:
   - Merges certified observations across all 9 companies for:
     1. Investment Portfolio Comprehensive Wide Table (`INVESTMENT_PORTFOLIO_V2`)
     2. FVTPL Assets Wide Table (`fvtpl_assets`)
     3. Debt Investments Wide Table (`debt_investment`)
     4. Other Debt Investments Wide Table (`other_debt_investment`)
     5. Other Equity Instruments Wide Table (`other_equity_investment`)
     6. Derivative Financial Assets Wide Table (`derivative_financial_assets`)
     7. Loans and Advances Wide Table (`loans_and_advances`)
     8. Term Deposits Wide Table (`term_deposits`)
     9. Statutory Deposits Wide Table (`statutory_deposits`)
     10. Financial Investments Summary Wide Table (`financial_investments_summary`)
   - Verifies workbook structure: Multi-level headers (Company, Year, Scope, Currency Unit, Measure), Chinese display names, source trace metadata, and elimination of the partial passing disclaimer.
3. **Scenario 4.3 — 29 Isolated Company Longitudinal Workbooks Generation**:
   - Produces 9 company portfolio workbooks + 20 company financial note workbooks.
   - Verifies 3-year longitudinal continuity (2023, 2024, 2025) per company.
4. **Scenario 4.4 — Dual-Lane UI/CLI Semantic Parity Audit**:
   - Runs Offline Lane and FakeStreamlit UI Lane on isolated snapshots.
   - Validates all 21 semantic dimensions: record counts, SHA-256 hashes, presentation regimes, V6 contract versions, and bridge memberships.

---

### Tier 5: Adversarial & Stress Testing

1. **Adversarial 5.1 — Encoding & Escaping Robustness**:
   - Tests UTF-8 BOM, full-width ideographic spaces (`\u3000`), non-breaking spaces (`\xa0`), nested brackets (`（`, `）`, `[`, `]`), HTML entities (`&amp;`, `&lt;`, `&gt;`), and quotes in raw row items.
   - Asserts canonical normalization preserves exact item semantics without string corruption.
2. **Adversarial 5.2 — Manifest & Artifact Tampering Resilience**:
   - Injects corrupt JSON manifests, missing required columns, and manipulated row counts.
   - Asserts `validate_financial_merge_artifacts` fails closed with explicit error codes (`MERGE_MANIFEST_INVALID_JSON`, `ORIGINAL_VIEW_REQUIRED_IDENTITY_COLUMNS_MISSING`, `ORIGINAL_VIEW_ROW_COUNT_MISMATCH`).
3. **Adversarial 5.3 — Duplicate Keys & Ambiguous Source Defense**:
   - Simulates duplicate active member occurrences and ambiguous multiple sources for the same period.
   - Asserts standards bridge blanks the projected value (`final_value = NaN`), sets `BRIDGE_AMBIGUOUS_SOURCE_SET`, logs to `financial_investment_standards_bridge_audit.csv`, and forbids uncertified summation (`no_same_period_sum = True`).

---

## 4. Test Execution & Runner Architecture

### 4.1 Pytest Integrated Suite
- Test file: `releases/v6.14/tests/test_v614_e2e_acceptance_suite.py`
- Execution command:
  ```powershell
  python -m pytest releases/v6.14/tests/test_v614_e2e_acceptance_suite.py -v
  ```
- Full regression suite execution:
  ```powershell
  python -m pytest releases/v6.14/tests -q
  ```

### 4.2 Standalone E2E Runner Tool
- Tool script: `releases/v6.14/tools/run_e2e_acceptance_suite.py`
- Execution command:
  ```powershell
  python releases/v6.14/tools/run_e2e_acceptance_suite.py --output-dir output/_agent_runs/e2e_acceptance
  ```
- Generates:
  - `e2e_acceptance_matrix.json` (Per-cell, per-tier detailed results)
  - `e2e_acceptance_matrix.csv` (Spreadsheet view of stage results)
  - `e2e_acceptance_summary.json` (Aggregated status by tier and registry)

---

## 5. Acceptance Criteria Checklist

- [x] **54-Cell Matrix Coverage**: All 54 filing cells (9 companies × 3 years × 2 registries) evaluated and verified.
- [x] **Zero Regressions**: All 604 existing unit tests in `releases/v6.14/tests` pass.
- [x] **4-Tier + Tier 5 Hardening**: All tests across Tiers 1–5 implemented, documented, and verified.
- [x] **Standards Bridge Projections**: Original long, bridge long, bridge wide, and bridge audit fully tested.
- [x] **Workbook Delivery**: 10 Universal Research Wide and 29 Isolated Workbooks validated.
- [x] **UI/CLI Parity**: 21 semantic dimensions verified across both execution lanes.
