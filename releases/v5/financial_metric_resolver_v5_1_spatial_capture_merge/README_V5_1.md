# Financial Metric Resolver v5.1 — Spatial Table Capture + Complete Merge Workspace

v5.1 replaces the fragile first-generation table-capture path with a spatial ROI engine and adds an end-to-end multi-company / multi-year merge workflow.

## 1. Three P0 table-capture failures fixed

The real failure pattern was:

```text
actual PDF:
手续费及佣金   2,011,583.45   2,117,405.27

old output:
2025 nan = 3.45
nan nan  = 201158
2024 ... = 2,117,405.27
```

and the capture continued far beyond the target note into unrelated later tables.

v5.1 addresses three root causes.

### P0-1 Numeric Fragment Reconstruction

Logical columns are defined by period-header x anchors first:

```text
2025年度        2024年度
    ↓               ↓
 anchor_0        anchor_1
```

A data row may be physically extracted as:

```text
2,
011,
583.
45
```

All fragments assigned to the same x-anchor are reconstructed deterministically:

```text
2, + 011, + 583. + 45
→ 2,011,583.45
```

The number of logical columns is no longer inferred from the number of numeric fragments found in a row.

### P0-2 Table Context Isolation

A target note title is a hard context reset.

```text
30. 业务及管理费和其他业务成本
```

cannot inherit a header from note 29.

Cross-page inheritance is allowed only *inside* the target table after its own root header has been established.

The default table-capture engine is now:

```text
SPATIAL_ROI_V1
```

The old table parser is fallback-only and the fallback is explicitly recorded in warnings.

### P0-3 Exact ROI Boundary

The capture region is:

```text
target note title bottom
        ↓
all content inside the note
        ↓
next numbered note title top
```

Same-page boundaries are supported.

Example:

```text
30. target note
... target table ...

31. next note
```

Everything at or below the actual y-coordinate of `31.` is excluded.

`max_pages` is only a fallback guard when no next-note boundary is found.

## 2. TOC false-positive resistance

Annual reports often contain the same note title in the table of contents.

v5.1 scores nearby evidence:

```text
period headers
multiple numeric table-like lines
```

so the actual note body is preferred over a TOC hit.

A manual PDF start-page override is still available.

## 3. Spatial table model

The engine uses PyMuPDF word coordinates.

Pipeline:

```text
Named Note Locator
→ ROI
→ Period Header Anchors
→ Logical Column Model
→ Spatial Row Reconstruction
→ Numeric Fragment Reconstruction
→ Row Hierarchy
→ Raw Long / Raw Wide
```

For continuation pages:

```text
repeated header exists
→ use current-page anchors

no repeated header
→ inherit normalized x-anchor ratios from root table page
```

## 4. Unit safety

A unit is used only when explicitly identified.

If no reliable unit exists:

```text
unit = UNKNOWN / blank
value_yuan = null
```

The engine does not guess `元`, `千元`, `万元`, etc. from value magnitude.

## 5. New complete Merge workspace

Sidebar now includes:

```text
整表抓取
合表
```

The Merge workspace takes multiple existing table-capture runs.

Typical workflow:

```text
Company A 2024 capture
Company A 2025 capture
Company B 2024 capture
Company B 2025 capture
        ↓
Canonical Table ID
        ↓
Merge Project
```

## 6. Merge data architecture

### Immutable evidence

```text
merge_raw_long.csv
```

Preserves:

```text
capture_run_id
company
document_year
table_id

raw_item
normalized_item
parent_section

value
unit
page
source_method
```

Mapping never overwrites this layer.

### Mapping queue

```text
merge_mapping_queue.csv
```

Contains:

```text
source_key
parent_section
normalized_item

occurrences
capture_count
companies
example_raw_items

suggested_canonical_item
suggestion_score

canonical_section
canonical_item
category
mapping_status
mapping_note
```

## 7. Safe mapping policy

### Exact identity

Same:

```text
parent_section
+
normalized_item
```

across multiple captures:

```text
AUTO_EXACT_IDENTITY
```

may automatically align.

### Existing taxonomy

Previously confirmed mappings:

```text
AUTO_TAXONOMY
```

### Different names

For example:

```text
职工薪酬
职工工资及福利费
```

are NOT silently merged.

They remain:

```text
UNMAPPED_PRESERVED
```

until the reviewer explicitly maps both to:

```text
canonical_item = 职工薪酬
mapping_status = CONFIRMED
```

Fuzzy similarity is suggestion-only.

## 8. Context-aware item identity

Mapping identity is not only the row label.

It includes:

```text
parent_section + normalized_item
```

This prevents a repeated name such as:

```text
其他业务成本
```

in different sections of the same note from being silently treated as the same row.

The reviewer can also standardize:

```text
canonical_section
```

when section names differ across companies.

## 9. Persistent Table Taxonomy

Confirmed mappings can be written to:

```text
workspace/table_taxonomy.json
```

Example:

```text
职工薪酬
职工工资及福利费
        ↓ confirmed
canonical_item = 职工薪酬
category = 人员成本
```

Future merge projects for the same Canonical Table ID automatically receive:

```text
AUTO_TAXONOMY
```

The taxonomy is separate from the single-metric `metric_aliases.json`.

## 10. Canonical materialization

Outputs:

```text
merge_canonical_long.csv
merge_resolved_long.csv
merge_canonical_wide.csv
```

`merge_canonical_long.csv` preserves source rows plus mapping fields.

`merge_resolved_long.csv` creates one resolved record per canonical natural key.

`merge_canonical_wide.csv` is the research-facing panel.

Typical structure:

```text
canonical_key
canonical_section
canonical_item
unit
A保险 | 2024 | 2024
A保险 | 2025 | 2025
B保险 | 2024 | 2024
B保险 | 2025 | 2025
```

## 11. Unmapped data is never lost

Unique unmapped items remain in the merged dataset with:

```text
RAW::<table>::<section>::<item>
```

They are visible but are not silently merged with differently named rows.

## 12. Conflict gate

Natural-key collisions are explicitly checked.

Examples:

```text
same canonical key
same company/year/scope
different values
→ VALUE_CONFLICT

same canonical key
incompatible units
→ UNIT_CONFLICT
```

Conflicted keys are written to:

```text
merge_conflicts.csv
```

and are blocked from `merge_canonical_wide.csv`.

No arbitrary `first()` value is silently accepted for a conflict.

## 13. Coverage report

```text
merge_coverage.csv
```

reports per capture:

```text
numeric_source_rows
mapped_or_exact_rows
unmapped_preserved_rows
mapping_coverage
project_conflict_count
```

## 14. Merge project outputs

Every merge project writes:

```text
merge_manifest.json

merge_raw_long.csv
merge_mapping_queue.csv

merge_canonical_long.csv
merge_resolved_long.csv
merge_canonical_wide.csv

merge_conflicts.csv
merge_coverage.csv

merge_project.xlsx
taxonomy_snapshot.json   # when taxonomy exists
```

Excel sheets:

```text
raw_long
mapping_queue
canonical_long
resolved_long
canonical_wide
conflicts
coverage
```

## 15. GUI mapping review

Inside `合表 → 映射审核`:

Editable:

```text
canonical_section
canonical_item
category
mapping_status
mapping_note
```

Protected evidence/suggestion fields remain read-only.

Saving performs:

```text
mapping save
→ optional taxonomy writeback
→ canonical rematerialization
→ conflict recomputation
→ coverage recomputation
```

## 16. Requested L0 metrics retained

v5.1 retains the v5.0 L0 additions:

```text
业务及管理费
```

strong aliases:

```text
业务及管理费用
业务管理费
```

and:

```text
支付给职工以及为职工支付的现金
```

strong aliases:

```text
支付给职工及为职工支付的现金
支付给职工以及为职工支付现金
```

`职工工资及福利费` is deliberately NOT an alias of the cash-flow item.

## 17. Validation performed

Automated regression tests passed for:

```text
numeric fragments:
2, + 011, + 583. + 45
→ 2,011,583.45
PASS

TOC title vs real note body
→ real note selected
PASS

same-page next-note ROI boundary
→ later note excluded
PASS

spatial capture wrapper
→ SPATIAL_ROI_V1
PASS

exact normalized cross-company item
→ AUTO_EXACT_IDENTITY
PASS

different employee-cost names
→ UNMAPPED_PRESERVED before review
PASS

human mapping to common canonical item
→ merged correctly
PASS

confirmed taxonomy persistence
→ next project AUTO_TAXONOMY
PASS

canonical wide
→ exactly one row per canonical key
PASS

duplicate key with different values
→ VALUE_CONFLICT
→ blocked from research wide
PASS
```

## 18. Important migration note

Old v5.0 `table_raw_*.csv` files are not automatically repaired because they may already contain incorrectly split numbers and over-captured rows.

For affected tables, re-run the original PDF through v5.1 `整表抓取`, then use the new `合表` workspace.

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

or:

```text
run_gui.bat
```
