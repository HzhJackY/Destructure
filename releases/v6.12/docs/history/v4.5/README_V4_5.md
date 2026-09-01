# Financial Metric Resolver v4.5 — Parallel Progress + Period Binding + Human Adjudication

v4.5 closes three production-critical gaps in v4.4.

## 1. Parallel batch jobs now show live progress

Each PDF reports its own state:

- waiting / running / done / error
- Fast Index page progress
- OCR stage
- candidate-page deep parse
- current PDF page
- L0/L1/L2 metric progress
- completed metric count
- final elapsed time

The GUI renders a live per-document status table and overall progress bar.

Worker progress is transmitted back to the main Streamlit process via a multiprocessing queue. Terminal `job_done` is emitted only after final worker progress events are drained, so a completed job will not visually regress to an earlier stage.

A new file is saved:

```text
batch_activity.log
```

## 2. Period binding fixed for shifted PDF table headers

A common PDF extraction pattern is:

```text
header row extracted as:
["2022年度", "2021年度"]

value row:
["净利润", "7,770,000.14", "134,342,343.93"]
```

Raw column indices are shifted because the blank first header cell was lost.

v4.4 could incorrectly bind:

```text
7,770,000.14 -> 2021年度
```

v4.5 uses ordinal left-to-right period binding when the number of period headers matches the number of numeric columns:

```text
2022年度 -> 7,770,000.14
2021年度 -> 134,342,343.93
```

The batch document year is also passed as a target-year constraint to primary-value selection.

For a 2022 report:

```text
document_year = 2022

2022年度  7,770,000.14
2021年度  134,342,343.93
```

the selected primary value is:

```text
7,770,000.14
value_year = 2022
```

## 3. Human review now materializes into final long/wide tables

Machine output is never overwritten.

v4.5 separates:

```text
machine_long.csv
machine_wide.csv
```

from final adjudicated outputs:

```text
adjudicated_long.csv
adjudicated_wide.csv
```

For backward compatibility:

```text
batch_long.csv
batch_wide.csv
```

now point to the FINAL adjudicated research view.

### Review behavior

`CONFIRMED_AUTO`

```text
final_value = machine_value
resolution_source = HUMAN_REVIEW
```

`CONFIRMED_OVERRIDE`

```text
final_value = frozen manually selected candidate value
resolution_source = HUMAN_REVIEW
```

`REJECTED`

```text
final_value = null
```

`UNRESOLVED`

```text
final_value = null
```

Unreviewed machine results enter the final table only when:

```text
machine_status == RESOLVED
```

Unreviewed `REVIEW_REQUIRED` values do not silently enter the research table.

## 4. Human review freezes the actual evidence

A manual override no longer stores only:

```text
candidate_id
```

It also freezes:

- chosen candidate
- page
- original label
- source method
- all candidate metadata
- chosen numeric column
- raw value
- parsed value
- unit
- table/header period
- chosen value year

This prevents future candidate reordering from changing the historical meaning of a human decision.

## 5. Excel structure

`batch_results.xlsx` contains:

```text
machine_long
machine_wide
adjudicated_long
adjudicated_wide
review_log
```

The final research table is:

```text
adjudicated_long
adjudicated_wide
```

The machine sheets remain immutable audit evidence.

## 6. GUI Reports & Audit

Batch mode now exposes:

- HTML total report
- Markdown
- final wide table
- final long table
- machine wide table
- machine long table
- machine JSON
- audit log
- parallel activity log
- human review log

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

or:

```text
run_gui.bat
```

## Validation performed

v4.5 was smoke-tested for:

1. shifted period header binding:
   - 2022 -> 7,770,000.14
   - 2021 -> 134,342,343.93
2. target-year primary-value selection
3. human override materialization
4. preservation of machine value and final value simultaneously
5. Excel five-sheet output
6. parallel worker live progress events
7. worker progress ordering before terminal `job_done`
