# Financial Metric Resolver v4.6 — Batch Identity / Review / Report Fix

v4.6 fixes two issues exposed by real batch output.

## 1. One PDF no longer splits into `<company>` and `<company> <year>` columns

Root causes in v4.5:

### A. Internal upload SHA leaked into company name

Uploaded files are stored internally as:

```text
91e001708c2b_中银三星2022年度信息披露报告.pdf
```

The old company inference could produce:

```text
91e001708c2b 中银三星
```

v4.6 strips the internal 12-hex storage prefix before company inference and display.

### B. pandas NaN was treated as a valid `value_year`

After machine results were converted to DataFrame, missing `value_year` could become `NaN`.

Old adjudication logic effectively behaved like:

```text
final_year = NaN
effective_year = NaN or document_year
```

Because float NaN is truthy in Python, the fallback to `document_year` did not happen.

This could split one 2022 PDF into:

```text
中银三星
中银三星 2022
```

v4.6 normalizes:

```text
None / NaN / NaT / "" / "none"
```

as missing and safely falls back:

```text
effective_year = value_year if valid else document_year
```

For one 2022 PDF, all metrics therefore remain under one column:

```text
中银三星 2022
```

## 2. Batch review / reports restored

v4.5 had a GUI branch assembly bug: batch report tabs were accidentally inserted under the single-PDF report branch.

v4.6 reconstructs the whole `报告与审计` page with explicit modes:

```text
单 PDF 运行
批量运行
```

Batch mode shows:

- HTML total report
- Markdown
- adjudicated/final wide table
- adjudicated/final long table
- machine wide table
- machine long table
- batch_results.json
- audit.jsonl
- batch_activity.log
- human_review.jsonl

## 3. Batch human-review fallback

For batch runs, review details are loaded from:

```text
batch_results.json -> resolution_details
```

If missing, v4.6 attempts to recover candidate-level details from:

```text
audit.jsonl
```

Old runs without either source cannot support candidate override, but their aggregate results remain viewable.

## 4. Old v4.5 batch runs can often self-heal

When opening a batch run in `报告与审计`, v4.6 attempts to rebuild missing final views from:

```text
batch_results.json
human_review.jsonl
```

using the corrected identity/year logic.

Therefore an old split:

```text
91e001708c2b 中银三星
91e001708c2b 中银三星 2022
```

can usually be rebuilt as:

```text
中银三星 2022
```

without re-parsing the PDF, provided `batch_results.json` exists.

## 5. Validation

Synthetic regression test:

One PDF:

```text
91e001708c2b_中银三星2022年度信息披露报告.pdf
```

with:
- 净利润: value_year=2022
- 货币资金: value_year missing

Expected wide table:

```text
metric | 中银三星 2022
```

and NOT:

```text
metric | 91e001708c2b 中银三星 | 91e001708c2b 中银三星 2022
```

Test passed.
