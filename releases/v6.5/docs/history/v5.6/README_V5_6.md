# Financial Metric Resolver v5.6
## Shared Data Home + Migration Center + Conditional Identity + Reconciliation Audit

v5.6 focuses on long-term data governance and fixes three structural extraction/merge issues:

1. Code versions and historical data are separated through a shared `DATA_HOME`.
2. Old versions can be migrated through a formal Migration Center.
3. Note numbers can be inferred automatically from located table titles.
4. `parent_section` no longer permanently blocks same-name item merging.
5. Total/subtotal arithmetic reconciliation is added as a warning-only audit.

---

# 1. Shared DATA_HOME

Before v5.6, each extracted application folder had its own:

```text
<version>/workspace/
```

That made upgrades fragile:

```text
v5.4/workspace
v5.5/workspace
v5.6/workspace
```

Historical data had to be copied manually.

From v5.6 onward:

```text
CODE_HOME != DATA_HOME
```

Default shared location:

```text
Windows:
C:\Users\<username>\FinancialMetricResolverData

macOS/Linux:
~/FinancialMetricResolverData
```

Directory structure:

```text
FinancialMetricResolverData/
├─ data_manifest.json
├─ uploads/
├─ runs/
├─ batch_runs/
├─ table_captures/
│  └─ _trash/
├─ table_merges/
│  └─ _trash/
├─ reviews/
├─ rule_backups/
├─ cache/
├─ config/
│  ├─ metric_aliases.json
│  └─ table_taxonomy.json
├─ archive/
└─ migration_reports/
```

All future code versions can point to the same data repository.

---

# 2. Stable DATA_HOME pointer across future versions

Resolution priority:

```text
1. FIN_METRIC_DATA_HOME environment variable
2. ~/.financial_metric_resolver/data_home.json
3. local code-folder data_home.json
4. ~/FinancialMetricResolverData
```

When the GUI changes DATA_HOME, v5.6 writes a stable user-level pointer:

```text
~/.financial_metric_resolver/data_home.json
```

Therefore a future v5.7/v5.8 code folder can automatically find the same custom DATA_HOME.

The GUI path:

```text
数据管理
→ 修改 DATA_HOME
```

requires a Streamlit restart after changing the location.

---

# 3. Historical Version Migration Center

GUI:

```text
数据管理
→ 历史版本迁移中心
```

Input can be either:

```text
D:\FinancialResolver\v5.5
```

or:

```text
D:\FinancialResolver\v5.5\workspace
```

The scanner reports:

```text
PDF count
Capture count
Merge count
Batch count
Run count
Review files
Taxonomy presence
metric_aliases presence
Cache presence
```

Migration policy:

```text
PDF
→ MIGRATE

Capture
→ MIGRATE + SCHEMA UPGRADE

Boundary Review / Header Review
→ PRESERVE

Table Taxonomy
→ MERGE

L0 metric_aliases
→ CONSERVATIVE MERGE

Batch / Runs / Reviews / Rule Backups
→ MIGRATE

Old Merge Projects
→ ARCHIVE_REBUILD_RECOMMENDED

Cache
→ SKIP
```

A machine-readable report is written to:

```text
DATA_HOME/migration_reports/migration_<timestamp>.json
```

---

# 4. Why old Merge Projects are archived instead of promoted

Capture is treated as a source asset.

Merge is a derived asset.

```text
PDF
↓
Machine Capture
↓
Human Boundary/Header Review
↓
Taxonomy
↓
Canonical Merge
```

Parser and canonicalization logic changed materially across v5.1–v5.6:

```text
Spatial ROI
Header Dimensions
Canonical Structural Order
Conditional Item Identity
```

Therefore an old:

```text
merge_canonical_wide.csv
```

may be stale even when its underlying Capture evidence is valuable.

Migration policy:

```text
old table_merges/
→ DATA_HOME/archive/legacy_merges_<timestamp>/
→ REBUILD_RECOMMENDED
```

The source Capture/history is preserved and should be used to create a new formal Merge under the latest rules.

---

# 5. Historical assets classified by permanence

Permanent assets:

```text
Original PDFs
Machine Capture
Human boundary adjudication
Human header-dimension adjudication
Taxonomy / confirmed mappings
```

Rebuildable derived assets:

```text
Canonical Merge
```

Temporary assets:

```text
Cache
```

This is the migration contract going forward.

---

# 6. Capture schema provenance

New v5.6 Capture JSON records:

```text
producer_version = v5.6
capture_schema_version = 5.6
reconciliation_schema_version = 1
```

Shared data manifest records:

```text
data_schema_version = 5.6
last_opened_by = v5.6
last_migrated_from
last_migration_report
```

This provides a formal basis for future schema migrations.

---

# 7. Automatic note-number inference

The user no longer needs to manually enter the note number in normal cases.

Input:

```text
目标表:
业务及管理费和其他业务成本

附注编号:
<blank>
```

Located title:

```text
34. 业务及管理费和其他业务成本
```

v5.6 infers:

```text
resolved_note_number = 34
note_number_source = INFERRED_FROM_LOCATED_TITLE
next_note = 35
```

Then:

```text
35. 下一附注
```

is used as the hard end boundary.

Supported common Arabic-number formats:

```text
34. 标题
34．标题
34、标题
34 标题
```

User-supplied note number remains higher priority:

```text
note_number_source = USER_PROVIDED
```

---

# 8. Hard-boundary false-positive protection

The next-note candidate must:

```text
match the expected next number
contain non-numeric heading text
be spatially close to the title/left heading alignment
```

A table value/data line such as:

```text
35 万元...
```

far inside the numeric region should not terminate the target note.

---

# 9. Conditional parent_section identity

Before v5.6:

```text
source identity =
parent_section + normalized_item
```

This was too strict.

Example:

```text
Company A:
parent_section = 按费用项目
item = 其他业务成本

Company B:
parent_section = 费用项目
item = 其他业务成本
```

Even though each table contained only one `其他业务成本`, they could fail to align.

v5.6 policy:

```text
If normalized_item appears only once in a source table:
    identity = normalized_item
    parent_section = context only

If normalized_item appears multiple times in the SAME source table:
    activate contextual disambiguation
```

Unique identity:

```text
UNIQUE||其他业务成本
```

Contextual duplicate identity:

```text
CONTEXT||
其他业务成本||
parent_section||
row_type||
occurrence
```

Thus `parent_section` is now:

```text
conditional disambiguation context
```

instead of:

```text
permanent primary key
```

---

# 10. Same-source duplicate safety

Example:

```text
按费用项目
  其他业务成本 = 342...

不可归属于保险合同组合的费用
  其他业务成本 = 126...
```

The same source contains two rows with the same name.

v5.6 does NOT collapse them.

It activates:

```text
parent_section
row_type
local occurrence order
```

to preserve two separate identities.

This retains the original safety objective without penalizing harmless cross-company parent-section text differences.

---

# 11. Backward-compatible Table Taxonomy

Older taxonomy keys may have been stored as:

```text
parent_section||item
```

v5.6 can reuse a legacy mapping for:

```text
UNIQUE||item
```

only when all matching legacy entries point to the same canonical target.

Ambiguous legacy mappings are not silently reused.

---

# 12. Total / Subtotal Reconciliation Audit

New output:

```text
table_reconciliation_audit.csv
```

Merge aggregation:

```text
merge_reconciliation_audit.csv
```

The key principle is:

```text
STRUCTURE → MEMBERSHIP
ARITHMETIC → VALIDATION
```

The system never searches combinations of rows merely because they happen to add up to a total.

---

# 13. Supported reconciliation patterns

## TRAILING_TOTAL

Example:

```text
手续费及佣金
职工薪酬
保险保障基金
...
其他费用
合计
```

Candidate children are inferred structurally from the preceding section/block.

Then:

```text
sum(children)
vs
reported 合计
```

is checked.

## LEADING_PARENT_TOTAL

Example:

```text
小计
  子项A
  子项B
  子项C
```

or:

```text
可归属于保险合同组合的费用
  计入未到期责任负债...
  计入保险服务费用...
```

Children are inferred from:

```text
row_level
parent_section
contiguous structural position
```

until a same/higher-level boundary is reached.

---

# 14. Reconciliation statuses

Possible statuses:

```text
PASS_EXACT
PASS_ROUNDING

WARNING_SUM_MISMATCH
WARNING_COMPONENT_SCOPE_AMBIGUOUS

NOT_TESTABLE_NO_CONFIDENT_CHILD_SET
NOT_TESTABLE_NO_TARGET_VALUE
```

This audit is warning-only.

It does NOT:

```text
change values
drop rows
alter taxonomy
block canonical wide by itself
```

The reviewer sees:

```text
target row
inferred child row_orders
child item names
reported total
calculated sum
difference
difference ratio
confidence
inference reason
```

---

# 15. Why reconciliation is warning-only

Real financial notes may contain:

```text
其中：...
partial disclosure
nested subtotal
overlapping components
sign/reclassification relationships
```

A naive sum can double-count.

Therefore:

```text
arithmetic mismatch != automatic data error
```

It is a review signal.

---

# 16. GUI reconciliation review

Current Capture:

```text
整表抓取
→ 合计/小计复核
```

Historical Capture:

```text
Capture Library
→ 合计/小计复核
```

Merge Project:

```text
合表
→ 合计/小计复核
```

The Merge view aggregates source-level reconciliation audits rather than inventing new membership after canonicalization.

---

# 17. Reconciliation outputs in Excel

`table_capture.xlsx` includes:

```text
reconciliation
```

`merge_project.xlsx` includes:

```text
reconciliation
```

This preserves the audit alongside the main data.

---

# 18. Existing v5.5 header-dimension safety retained

Multi-level columns remain protected:

```text
2022 本集团
2021 本集团
2022 本公司
2021 本公司
```

Header collisions still trigger:

```text
HEADER_DIMENSION_COLLISION
REVIEW_REQUIRED
```

and block formal Merge until reviewed.

---

# 19. Existing v5.4 structural ordering retained

Canonical Merge still uses:

```text
canonical_order
reference_capture_run_id
```

and preserves:

```text
小计
  明细
合计
```

without groupby/pivot/alphabetical reordering.

---

# 20. Existing v5.3/v5.2/v5.1 functionality retained

Retained:

```text
Boundary Review
Capture Library
Merge Library
soft delete / recycle bins

Source Quality Arbitration
semantic_score / evidence_quality / arbitration_score

Custom CSV location and filename

Spatial ROI Table Capture
numeric-fragment reconstruction
Table Taxonomy
conflict gates
```

---

# 21. Recommended first upgrade from v5.5

1. Launch v5.6.
2. Open:

```text
数据管理
```

3. Confirm shared DATA_HOME.
4. Under:

```text
历史版本迁移中心
```

select the old v5.5 folder.
5. Scan.
6. Review migration plan.
7. Execute migration.
8. Review `migration_report.json`.
9. Rebuild formal Merge Projects from migrated Captures where required.

After this first migration, future code upgrades should normally continue using the same DATA_HOME without copying history again.

---

# Validation

Automated regression tests passed for:

```text
AUTO_NOTE_NUMBER_INFERENCE_FROM_LOCATED_TITLE
PASS

next-note hard boundary with spatial false-positive protection
PASS

hierarchical 本集团 / 本公司 header binding
PASS

header collision gate + human correction
PASS

same-name unique item across different parent_section
→ AUTO_EXACT_IDENTITY
PASS

same-source repeated item
→ CONTEXTUAL disambiguation
PASS

canonical structural order survives rematerialization
PASS

TOTAL reconciliation mismatch
→ WARNING_SUM_MISMATCH
PASS

shared DATA_HOME migration
PASS

old Merge archive / rebuild-recommended policy
PASS
```

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

or:

```text
run_gui.bat
```
