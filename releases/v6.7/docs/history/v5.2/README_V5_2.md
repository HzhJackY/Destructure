# Financial Metric Resolver v5.2 — Source Quality Arbitration + Custom CSV Export

v5.2 fixes a candidate-selection failure exposed by real extraction runs:

```text
Candidate A:
exact metric label
value
period/header
unit
structured table source

Candidate B:
exact metric label
value
period/header
MISSING UNIT

old UI:
A score = 1.0
B score = 1.0

old result:
tie/order could select B
→ downstream REVIEW_REQUIRED
```

The root problem was that one saturated rule score was being asked to represent two different questions:

```text
1. Is this the right accounting metric?
2. Is this the best available evidence source?
```

v5.2 separates them.

## 1. Three-score candidate model

Every candidate now has:

```text
semantic_score
evidence_quality
arbitration_score
```

### semantic_score

Answers:

```text
Is the label semantically the requested metric?
```

Exact standard labels can still legitimately score:

```text
1.000
```

Multiple exact sources may all have semantic score 1.0.

### evidence_quality

Answers:

```text
How complete and auditable is the extracted evidence?
```

Signals include:

```text
numeric presence
numeric parse completeness
period/header presence
period/header strength
unit presence
unit compatibility with value_type
source-method quality
known table type
header provenance
```

Example regression:

```text
complete exact candidate
semantic_score  = 1.000
evidence_quality = 0.940
arbitration_score = 0.9832

same exact candidate but missing unit
semantic_score  = 1.000
evidence_quality = 0.690
arbitration_score = 0.9132
```

The complete candidate wins deterministically.

## 2. Evidence-quality hierarchy

When semantic class is the same, ranking prioritizes:

```text
evidence_quality
→ arbitration_score
→ source-method quality
→ numeric evidence
→ semantic score
```

Therefore:

```text
label + header + value + compatible unit
```

outranks:

```text
label + header + value + missing unit
```

even when both labels are exact and both semantic scores are 1.0.

Structured native table evidence also outranks coordinate/recovery evidence when completeness is otherwise equal.

## 3. Exact-label arbitration fixed

Old exact-label logic:

```text
exact candidates
→ sort mainly by rule score
→ saturated ties possible
```

v5.2:

```text
exact candidates
→ semantic class locked
→ rank by evidence quality
→ select best complete evidence
```

Decision reason is auditable, for example:

```text
exact_label_best_evidence_quality=0.940_vs_0.690
```

## 4. UI no longer shows one ambiguous "score"

Top-candidate review now displays:

```text
语义分
证据质量
综合裁决分
单位完整
期间/表头完整
```

This makes two `1.000` semantic matches visibly different.

## 5. L2 receives evidence quality

DeepSeek/Gemini bounded-choice payload now includes:

```text
semantic_score
evidence_quality
arbitration_score
evidence_detail
```

The L2 contract explicitly says:

```text
when semantic matches are equivalent,
prefer evidence with:
- numeric value
- period/header
- compatible unit
- structured table provenance
```

LLM still cannot invent values, units, pages, or labels.

## 6. Reports updated

Markdown/HTML reports now distinguish:

```text
语义分
证据质量
综合裁决分
```

instead of presenting only a saturated rule score.

## 7. Custom CSV output location and filename

v5.2 adds direct local CSV saving in addition to browser downloads.

User can specify:

```text
保存目录:
D:\insurance_research\data

文件名:
中国保险公司_业务管理费_2025.csv
```

If `.csv` is omitted, it is appended automatically.

Directories are created automatically when needed.

Overwrite protection is enabled by default:

```text
existing file
→ refuse overwrite

check "允许覆盖同名文件"
→ overwrite allowed
```

## 8. Custom export coverage

Available for batch metric outputs:

```text
adjudicated_wide.csv
adjudicated_long.csv
machine_wide.csv
machine_long.csv
```

Available for Table Capture:

```text
table_raw_long.csv
table_raw_wide.csv
table_item_dictionary.csv
```

Available for Merge projects:

```text
merge_raw_long.csv
merge_mapping_queue.csv
merge_canonical_long.csv
merge_resolved_long.csv
merge_canonical_wide.csv
merge_conflicts.csv
merge_coverage.csv
```

Original browser download buttons remain available.

## 9. Validation

Regression test:

```text
same exact label
same numeric values
same periods

Candidate A:
unit = 万元

Candidate B:
unit = missing

both semantic_score = 1.0

result:
Candidate A evidence_quality = 0.940
Candidate B evidence_quality = 0.690

selected = Candidate A
PASS
```

Source provenance test:

```text
structured pdfplumber table
vs
coordinate-row source

otherwise equal
→ structured table wins
PASS
```

Custom export test:

```text
custom nested directory
custom Chinese filename
automatic .csv suffix
overwrite guard
explicit overwrite

PASS
```

## 10. Retained functionality

v5.2 retains all v5.1 functionality:

```text
Spatial ROI Table Capture
numeric fragment reconstruction
exact note ROI boundaries
TOC false-positive resistance
cross-page continuation
complete Merge workspace
persistent Table Taxonomy
canonical long/wide
conflict gates
coverage reports
```

It also retains all earlier metric extraction, L0/L1/L2, human review, percentage safety, and unit-column output fixes.

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

or use:

```text
run_gui.bat
```
