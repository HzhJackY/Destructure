# Financial Metric Resolver v5.9
## Dual Header Parser Arbitration + Human Parser Selection + Safe Topology Review

v5.9 addresses a parser regression observed after adding v5.7 relative-period support.

A standard annual-report table such as:

```text
                 本集团                    本公司
          2024年度  2023年度(已重述)  2024年度  2023年度(已重述)
```

has four real numeric columns.

Some v5.7/v5.8 PDFs could be over-segmented into eight logical columns because the generalized period parser simultaneously generated overlapping candidates such as:

```text
2024
2024年度
```

or:

```text
2023
2023年度（已重述）
```

v5.9 does not solve this by removing the v5.7 parser.

Instead it introduces two independent header experts, an independent topology referee, automatic arbitration, manual parser selection, and a safe topology-review fallback.

---

# 1. Two independent header parsers

## Parser A — ABSOLUTE_YEAR_CLASSIC

Designed for traditional financial-statement headers:

```text
2025
2024
2025年度
2024年度
2023年度（已重述）
```

Key properties:

```text
explicit absolute-year focus
conservative 20xx recognition
maximal physical span
no relative-period expansion
```

Example:

```text
PDF words:
2024 + 年度
```

becomes one leaf:

```text
2024年度
```

not:

```text
2024
2024年度
```

two separate logical columns.

---

## Parser B — GENERALIZED_PERIOD_V57

The v5.7 generalized parser remains available for:

```text
本年累计数
上年累计数
去年累计数
本期 / 上期
期末 / 期初
```

and keeps v5.7 functionality:

```text
本集团 / 本公司 hierarchical headers
relative-period reconstruction
split-word period labels
wrapped accounting rows
blank-value detail rows
formula reconciliation
```

The old parser is therefore not restored by deleting the new one.

Both experts coexist.

---

# 2. Generalized parser also gains maximal-span dedup

Even Parser B now performs stronger physical overlap deduplication.

Candidates:

```text
2024
2024年度
```

with:

```text
same semantic year
same baseline
overlapping bounding boxes
```

collapse to one maximal span.

Likewise:

```text
本年
本年累计数
```

from the same physical word region cannot become two leaf columns.

---

# 3. Independent Numeric Column Cluster Referee

Header parsers are not allowed to judge themselves.

v5.9 scans repeated numeric x-positions in the table body independently.

Example body:

```text
工资及福利费       494040164  450070257  453567201  405062799
服务费             101286372  105996040   84753451   91631416
...
```

Stable numeric body geometry:

```text
numeric_cluster_count = 4
```

If a parser returns:

```text
header_leaf_count = 8
```

the candidate is rejected with:

```text
HEADER_OVERSEGMENTATION_VS_NUMERIC_CLUSTERS
```

This is the primary protection against the reported 4→8 regression.

---

# 4. Hierarchical Cardinality Referee

The referee also inspects parent scope headers.

Example:

```text
本集团
本公司
```

with two stable numeric columns under each group implies a four-column topology.

Candidates inconsistent with the group structure can receive:

```text
HIERARCHICAL_CARDINALITY_MISMATCH
```

The parent-scope binding itself was also hardened:

```text
本集团 / 本公司
```

now uses midpoint/Voronoi regions between parent centers.

This prevents a visually wide leaf such as:

```text
2023年度（已重述）
```

from shifting its center enough to lose the correct parent scope.

---

# 5. Restated is a leaf annotation, not a parent span

`已重述 / 经重述 / 重述后` is now bound separately from parent scope headers.

Correct result:

```text
2024 | 本集团 | restated=False
2023 | 本集团 | restated=True
2024 | 本公司 | restated=False
2023 | 本公司 | restated=True
```

A restated label no longer propagates across an entire `本集团` or `本公司` group.

---

# 6. Arbitration hard rules

Each parser candidate is evaluated using:

```text
leaf_count
numeric_cluster_count
parent_scope_count
scope_coverage
dimension uniqueness
header-to-numeric alignment
duplicate semantic dimensions
```

Hard failures include:

```text
DUPLICATE_DIMENSION_KEYS

HEADER_OVERSEGMENTATION_VS_NUMERIC_CLUSTERS

HEADER_UNDERSEGMENTATION_VS_NUMERIC_CLUSTERS

HIERARCHICAL_CARDINALITY_MISMATCH
```

Hard rules run before score comparison.

A candidate that fails a hard topology rule cannot win merely because its heuristic score is high.

---

# 7. Scoring is secondary

Only candidates that pass hard validation compete by score.

Typical standard table:

```text
ABSOLUTE_YEAR_CLASSIC
leaf_count             4
numeric_clusters       4
scope_coverage         4/4
duplicate_dimensions   0
status                 VALID
score                  high

GENERALIZED_PERIOD_V57
also valid
```

For explicit absolute-year tables, Classic receives a small stability prior.

Typical result:

```text
AUTO_SELECTED = ABSOLUTE_YEAR_CLASSIC
```

---

# 8. Relative-period tables preserve v5.7 behavior

Example:

```text
                 本集团                    本公司
          本年累计数 上年累计数      本年累计数 上年累计数
```

Classic produces no usable relative-period candidate.

Generalized produces:

```text
本年累计数 | 本集团
上年累计数 | 本集团
本年累计数 | 本公司
上年累计数 | 本公司
```

Result:

```text
AUTO_SELECTED = GENERALIZED_PERIOD_V57
```

This is a fixed release regression test.

---

# 9. AUTO abstains when both candidates are unsafe

v5.9 does not always choose “the slightly better bad result”.

If neither candidate passes topology validation:

```text
HEADER_TOPOLOGY_REVIEW_REQUIRED
```

is raised.

This safety abstention is not allowed to silently fall back to the legacy parser.

Therefore:

```text
both unsafe
→ stop/review
```

not:

```text
both unsafe
→ pick highest score anyway
→ continue canonical merge
```

---

# 10. Manual parser mode before extraction

The GUI now provides:

```text
表头算法模式
```

Options:

```text
AUTO — 双算法并行 + 独立裁判（推荐）

ABSOLUTE_YEAR_CLASSIC — 传统绝对年份专家

GENERALIZED_PERIOD_V57 — 本年/去年/复杂期间专家
```

This allows deliberate comparison and reproducibility.

A user override is recorded as:

```text
HEADER_PARSER_USER_OVERRIDE
```

and the auto recommendation remains visible for audit.

---

# 11. Human Parser Arbitration Review after extraction

Current and historical Capture views now include:

```text
表头算法裁决
```

It displays side-by-side:

```text
parser
status
score
leaf columns
numeric clusters
scope coverage
duplicate dimensions
hard failures
column preview
```

Example:

```text
ABSOLUTE_YEAR_CLASSIC
4 leaves
4 numeric clusters
VALID

GENERALIZED_PERIOD_V57
8 leaves
4 numeric clusters
REJECTED
HEADER_OVERSEGMENTATION_VS_NUMERIC_CLUSTERS
```

The reviewer can select either available parser.

To preserve machine evidence, the system does not overwrite the original Capture.

Instead:

```text
用所选算法创建新的 Capture
```

creates a new historical Capture using the same source PDF and selected parser.

The original automatic Capture remains intact.

---

# 12. Machine arbitration artifacts

Each new Capture writes:

```text
machine_header_arbitration.json

header_parser_candidates.csv
```

The CSV contains candidate-level and column-level diagnostics.

`table_capture.xlsx` includes:

```text
header_candidates
header_arbitration
```

These sheets survive later boundary/header rematerialization.

---

# 13. Safe Column Topology Review fallback

The GUI also adds:

```text
列拓扑复核
```

Current supported actions:

```text
KEEP

DROP_DUPLICATE
```

This is specifically useful when a machine result already contains duplicated logical columns such as:

```text
2024 本集团
2024 本集团

2023 本集团
2023 本集团

2024 本公司
2024 本公司

2023 本公司
2023 本公司
```

The reviewer can retain four and drop four false duplicates.

Contract:

```text
machine evidence remains unchanged

official output is rematerialized from active columns

column_topology_review.json records the adjudication
```

---

# 14. Topology Review is intentionally conservative

v5.9 does NOT automatically concatenate conflicting physical value fragments.

Current manual topology actions are deliberately limited to:

```text
KEEP
DROP_DUPLICATE
```

A true case requiring:

```text
MERGE_PHYSICAL_COLUMNS
```

where two physical columns contain complementary numeric fragments is not guessed.

The recommended order is:

```text
1. AUTO arbitration
2. inspect Classic / Generalized
3. manually select the better parser
4. only then use safe KEEP/DROP topology review
```

This limitation is deliberate to avoid inventing or corrupting financial values.

---

# 15. Topology Review and Header Dimension Review are separate

Correct workflow:

```text
Column Topology Review
Which machine columns should exist?

        ↓

Header Dimension Review
What does each surviving column mean?

year
scope
restated
```

A topology review filters active columns before the dimension review.

The dimension editor therefore only edits active columns.

---

# 16. Reported 8-column pattern is now a frozen regression case

Reported bad machine topology:

```text
0  2024  None
1  2024  None
2  2023  本集团  restated
3  2023  本集团  restated
4  2024  None
5  2024  None
6  2023  本公司  restated
7  2023  本公司  restated
```

Expected topology:

```text
2024 | 本集团 | ORIGINAL
2023 | 本集团 | RESTATED
2024 | 本公司 | ORIGINAL
2023 | 本公司 | RESTATED
```

v5.9 regression checks:

```text
STANDARD_4COL_NOT_8_PASS
```

and fragmented source words:

```text
2024 + 年度
```

must satisfy:

```text
PERIOD_MAXIMAL_SPAN_DEDUP_PASS
```

---

# 17. v5.7 solved cases are fixed release gates

A permanent test corpus is included:

```text
tests/regression_v59.py
```

Windows launcher:

```text
run_regression_v59.bat
```

Release-gate cases include:

```text
A. split 2025 + 年度 / 2024 + 年度
   → 4 leaves, never 8

B. standard 2024 / 2023(已重述)
   → 4 columns with correct scope/restated

C. Generalized parser on standard table
   → still 4 columns

D. v5.7 relative periods
   → Generalized selected automatically

E. v5.7 wrapped accounting labels
   → preserved

F. v5.7 BASE_MINUS_COMPONENTS reconciliation
   → preserved

G. 8-header vs 4 numeric clusters
   → oversegmentation rejected

H. safe topology DROP_DUPLICATE
   → machine 8 preserved, official 4

I. v5.8 relative→absolute year resolution
   → preserved

J. arbitration audit artifacts
   → present
```

A release should not be accepted if any of these fail.

---

# 18. Regression results for this build

```text
PERIOD_MAXIMAL_SPAN_DEDUP_PASS

STANDARD_4COL_NOT_8_PASS

GENERALIZED_STANDARD_COMPAT_PASS

V57_RELATIVE_WRAPPED_FEATURES_PASS

V57_FORMULA_RECONCILIATION_PASS

NUMERIC_CLUSTER_REFEREE_PASS

SAFE_TOPOLOGY_DROP_PASS

V58_ABSOLUTE_YEAR_RESOLUTION_PASS

ARBITRATION_AUDIT_ARTIFACTS_PASS

ALL_V59_REGRESSION_CORPUS_PASS
```

---

# 19. Retained v5.8 functionality

v5.9 retains:

```text
本年/本期 → actual document_year

去年/上年/上期 → document_year - 1

source_period_label audit preservation

PERIOD_RESOLUTION_REQUIRED hard gate

old v5.7 Merge rematerialization repair
```

---

# 20. Retained v5.7 functionality

v5.9 retains:

```text
relative-period headers
no-note-number body location
wrapped accounting labels
blank-value detail preservation
BASE_MINUS_COMPONENTS / BASE_PLUS_COMPONENTS
warning-only reconciliation
```

---

# 21. Retained data governance

Shared DATA_HOME remains unchanged.

Existing historical assets continue to be used:

```text
PDF
Capture
Boundary Review
Header Review
Taxonomy
```

No workspace migration is required merely for v5.8 → v5.9.

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

or:

```text
run_gui.bat
```
