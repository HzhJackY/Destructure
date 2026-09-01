# Financial Metric Resolver v4.7 — Semantic + Value-Recovery Hardening

v4.7 builds on v4.6 and fixes a broader class of real-PDF failures rather than only one screenshot.

## 1. Candidate Value Recovery Layer

Problem pattern:

```text
PDF visually:
经营活动产生的现金流量净额   22,560,377,801.28   23,082,763,081.49

coordinate_rows extracted:
["经营活动产生的现金流量净额"]
["22,560,377,801.28", "23,082,763,081.49"]
```

Old behavior:

```text
candidate label found
values = []
→ L2 / human review sees only label
```

v4.7 recovery order:

```text
A. adjacent numeric continuation row
B. same-page cross-block equivalent label with values
C. nearby equivalent label row in same block
```

Every recovered value must already exist in deterministic PDF extraction.
The system never invents an amount.

Recovered source examples:

```text
coordinate_rows+adjacent_numeric_recovery
coordinate_rows+cross_block:pdfplumber_table
coordinate_rows+nearby_row_recovery
```

## 2. Period binding remains active after recovery

Recovered numeric rows are still bound to table period headers.

Example:

```text
2025年度   2024年度
经营活动产生的现金流量净额
22,560,377,801.28   23,082,763,081.49
```

becomes:

```text
22,560,377,801.28 -> 2025年度
23,082,763,081.49 -> 2024年度
```

For target document year 2025:

```text
primary_value = 22,560,377,801.28
```

## 3. Cash-flow semantic families: 产生 / 使用

For the same activity class:

```text
投资活动产生的现金流量净额
投资活动使用的现金流量净额
```

are treated as variants of the same canonical net cash-flow metric.

This is implemented for:

```text
经营活动
投资活动
筹资活动
```

The L0 rulebook now includes direction-wording aliases and semantic metadata:

```text
semantic_family = NET_CASH_FLOW_BY_ACTIVITY
activity_type = OPERATING / INVESTING / FINANCING
```

The L2 prompt also explicitly knows:

```text
same activity + same net cash-flow concept
产生 vs 使用
!= automatically different metric
```

Therefore L2 should not abstain solely because of the words `产生` vs `使用`.

## 4. Cash-flow sign safety

The system NEVER silently flips a sign.

Safe example:

```text
投资活动使用的现金流量净额   (1,250,000)
→ parsed = -1,250,000
→ may resolve
```

Ambiguous example:

```text
投资活动使用的现金流量净额   1,250,000
```

Because the label implies net outflow but raw number is positive:

```text
REVIEW_REQUIRED
reason = SIGN_SEMANTICS_CONFLICT
```

Human review decides the report convention.

## 5. Value-type compatibility guard

Prevents semantic/value-type confusion such as:

```text
核心偿付能力充足率
```

being associated with:

```text
核心偿付能力溢额  1,246,100万元
```

Rules:

```text
percentage metric + % value
→ bonus

percentage metric + monetary unit
→ strong penalty / REVIEW_REQUIRED if selected

monetary metric + %
→ REVIEW_REQUIRED
```

This specifically protects regulatory ratios, margins and rates from monetary-value misbinding.

## 6. Numeric continuation rows support missing placeholders

Recovery supports:

```text
["5,000.00", "-"]
["5,000.00", "—"]
["5,000.00", "不适用"]
```

instead of requiring every cell to contain a numeric value.

## 7. L2 candidate payload improved

L2 now receives:

```text
has_values
value_count
recovery_evidence
```

and semantic metadata:

```text
value_type
semantic_family
activity_type
direction_wording_equivalent
```

LLM remains bounded-choice only:

```text
select existing candidate_id
or abstain
```

It still cannot invent amounts, pages or rows.

## 8. Human review behavior

Because recovery happens BEFORE final resolution and before `resolution_details` are written,
the batch/single-PDF human review UI now sees recovered values directly.

Expected review display:

```text
p.9 · 经营活动产生的现金流量净额
source:
coordinate_rows+adjacent_numeric_recovery

2025年度 | 22,560,377,801.28
2024年度 | 23,082,763,081.49
```

The reviewer can select the exact period/value column before confirming or overriding.

## 9. v4.6 fixes retained

v4.7 retains:

- internal SHA prefix no longer leaks into company names
- one PDF no longer splits into blank-year / explicit-year columns
- pandas NaN year handling
- parallel per-PDF live progress
- batch human review
- batch report/audit tabs
- machine vs adjudicated data separation
- human review materialization into final long/wide tables
- 2022/2021 shifted period-header binding

## Validation performed

Regression tests passed for:

1. label-only row + adjacent numeric row recovery
2. 2025 / 2024 period binding after recovery
3. `产生` / `使用` cash-flow semantic alias
4. negative accounting parentheses preservation
5. positive `使用` sign-semantics conflict -> REVIEW_REQUIRED
6. same-page cross-block value recovery
7. percentage-vs-monetary type guard
8. missing-value placeholder continuation rows
9. v4.6 one-PDF-one-column identity regression

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
