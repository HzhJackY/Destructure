# CHANGELOG v5.9

## P0 — Dual Header Parser Architecture
- Added `ABSOLUTE_YEAR_CLASSIC`.
- Retained `GENERALIZED_PERIOD_V57`.
- Both parsers generate independent complete header candidates.
- Candidate parts are never mixed across parsers.

## Absolute-Year Regression Fix
- Added conservative classic parsing for explicit `20xx` headers.
- Added maximal-span dominance for split PDF words.
- Prevents:
  - `2024`
  - `2024年度`
  from becoming two physical leaf columns.
- Fixed reported 4-real-column → 8-machine-column regression.

## Generalized Parser Hardening
- Added bbox-overlap semantic dedup.
- Preserves v5.7 relative-period support.
- `本年/上年/去年/本期/上期` behavior retained.

## Independent Numeric Referee
- Added body numeric x-cluster inference.
- Added:
  - HEADER_OVERSEGMENTATION_VS_NUMERIC_CLUSTERS
  - HEADER_UNDERSEGMENTATION_VS_NUMERIC_CLUSTERS
- Header topology is validated independently from the parser.

## Hierarchical Referee
- Added parent scope cardinality checks.
- Added `HIERARCHICAL_CARDINALITY_MISMATCH`.
- Upgraded parent scope binding to midpoint/Voronoi regions.

## Restated Binding Fix
- Separated restated leaf annotations from parent-scope span binding.
- Correctly supports:
  - 2024 本集团 ORIGINAL
  - 2023 本集团 RESTATED
  - 2024 本公司 ORIGINAL
  - 2023 本公司 RESTATED

## Arbitration
- Added hard-rule-first arbitration.
- Score comparison only applies after hard validation.
- Classic receives a small stability prior on valid absolute-year tables.
- Relative-only tables naturally select Generalized.
- Added `HEADER_TOPOLOGY_REVIEW_REQUIRED`.
- Safety abstention cannot silently fall back to legacy.

## GUI Parser Selection
- Added parser mode:
  - AUTO
  - ABSOLUTE_YEAR_CLASSIC
  - GENERALIZED_PERIOD_V57
- Added `表头算法裁决` tab.
- Shows candidate metrics and column previews.
- Human parser choice creates a NEW Capture, preserving original machine evidence.

## Audit Artifacts
- Added:
  - machine_header_arbitration.json
  - header_parser_candidates.csv
- Added Excel sheets:
  - header_candidates
  - header_arbitration
- Rematerialization/boundary review preserves these audit sheets.

## Safe Column Topology Review
- Added `column_topology_review.py`.
- GUI `列拓扑复核`.
- Supports:
  - KEEP
  - DROP_DUPLICATE
- Machine full evidence remains immutable.
- Official output filters dropped false columns.
- Added `column_topology_review.json`.
- Header Dimension Review operates only on active topology columns.
- True value-fragment MERGE is deliberately not guessed in v5.9.

## Permanent Regression Corpus
- Added:
  - tests/regression_v59.py
  - run_regression_v59.bat
- Fixed release gates for v5.7/v5.8 solved cases and the 4→8 regression.

## Regression PASS
- PERIOD_MAXIMAL_SPAN_DEDUP_PASS
- STANDARD_4COL_NOT_8_PASS
- GENERALIZED_STANDARD_COMPAT_PASS
- V57_RELATIVE_WRAPPED_FEATURES_PASS
- V57_FORMULA_RECONCILIATION_PASS
- NUMERIC_CLUSTER_REFEREE_PASS
- SAFE_TOPOLOGY_DROP_PASS
- V58_ABSOLUTE_YEAR_RESOLUTION_PASS
- ARBITRATION_AUDIT_ARTIFACTS_PASS
- ALL_V59_REGRESSION_CORPUS_PASS
