# Financial Metric Resolver v5.8
## Absolute Year Resolution for Relative Period Labels

v5.8 fixes a Merge-layer period identity bug involving annual-report columns such as:

```text
本年
去年
本年累计数
去年累计数
上年累计数
本期累计数
上期累计数
```

These labels are relative to the report year and must never remain as the formal `year` key in canonical Merge output.

---

# 1. Correct period contract

For a 2023 annual report:

```text
document_year = 2023

本年 / 本年累计数 / 本期累计数
→ year = 2023

去年 / 去年累计数
上年 / 上年累计数
上期 / 上期累计数
→ year = 2022
```

The original PDF wording is preserved separately:

```text
source_period_label
```

Example:

```text
document_year  source_period_label  year
2023           本年累计数             2023
2023           去年累计数             2022
```

Canonical Merge therefore uses actual calendar years while retaining source evidence.

---

# 2. Root cause fixed: document_year was sometimes inferred from relative labels

A v5.7 Capture with columns:

```text
本年累计数
上年累计数
```

could reach this logic:

```python
document_year = max(years)
```

where `years` contained relative strings.

That could incorrectly produce:

```text
document_year = 上年累计数
```

instead of:

```text
document_year = 2022
```

Then the relative-period conversion function had no valid four-digit report year and could not resolve:

```text
本年累计数
上年累计数
```

v5.8 fixes this invariant:

```text
document_year must be an absolute four-digit year only.
```

Relative column labels are never eligible as document identity.

Inference order:

```text
1. explicit user-edited document_year
2. year in source PDF filename
3. absolute year evidence in capture columns/header
4. otherwise blank → manual review required
```

---

# 3. `去年` is now a first-class prior-period token

v5.8 formally supports:

Current/report-year labels:

```text
本年
本年度
本年累计数
本年度累计数
本期
本期数
本期累计数
当期
当期累计数
```

Prior-year labels:

```text
去年
去年累计数
去年数
去年同期

上年
上年度
上年累计数
上年度累计数
上年同期

上期
上期数
上期累计数
```

---

# 4. Spatial table capture also recognizes `去年 / 去年累计数`

This fix is not limited to Merge.

The spatial header parser now recognizes:

```text
本年累计数 | 去年累计数
```

as a valid relative-period header pair.

This prevents a PDF using `去年累计数` instead of `上年累计数` from failing during table-header construction.

---

# 5. Hard Merge safety gate

Formal canonical Merge may not contain unresolved relative values in `year`.

If a source contains:

```text
year = 本年
year = 去年
```

but the report year cannot be determined, v5.8 raises:

```text
PERIOD_RESOLUTION_REQUIRED
```

with guidance to set:

```text
document_year = actual annual-report year
```

Example:

```text
document_year = 2023
```

Then:

```text
本年 → 2023
去年 → 2022
```

The system no longer silently allows relative labels to collide downstream.

If `document_year` is known but a relative label somehow remains, it raises:

```text
PERIOD_RESOLUTION_INVARIANT_VIOLATION
```

and blocks canonicalization.

---

# 6. Existing v5.7 Merge Projects can be repaired

v5.8 does not require rebuilding every old Merge from scratch.

When an existing Merge Project is rematerialized:

```text
保存映射并重新物化合表
```

the system re-reads each source in the manifest and repairs:

```text
document_year
year
column_dimension_key
```

Example old v5.7 state:

```text
document_year = 本年累计数
year = 本年累计数 / 去年累计数
```

After v5.8 rematerialization:

```text
document_year = 2023
year = 2023 / 2022
source_period_label = 本年累计数 / 去年累计数
```

This repair also runs on every new Merge Project before canonicalization.

---

# 7. Raw source wording remains auditable

v5.8 deliberately separates:

```text
source_period_label
```

from:

```text
year
```

Example:

```text
source_period_label = 去年累计数
year = 2022
```

Therefore the system does not rewrite historical evidence.

It normalizes only the formal analytical dimension.

---

# 8. Multi-year example

2022 annual report:

```text
本年累计数 → 2022
上年累计数 → 2021
```

2023 annual report:

```text
本年累计数 → 2023
去年累计数 → 2022
```

Merge raw output:

```text
capture  document_year  source_period_label  year
2022     2022           本年累计数             2022
2022     2022           上年累计数             2021
2023     2023           本年累计数             2023
2023     2023           去年累计数             2022
```

No `本年累计数 / 去年累计数` remains in the canonical `year` dimension.

---

# 9. GUI guidance

The Merge source metadata section now explicitly states:

```text
document_year 必须是年报实际年份（四位数）
```

and explains:

```text
本年/本期 → document_year
去年/上年/上期 → document_year - 1
```

The original relative wording remains in:

```text
source_period_label
```

---

# 10. Validation

Automated tests passed:

```text
2022 report:
本年累计数 → 2022
上年累计数 → 2021

PASS
```

```text
2023 report:
本年累计数 → 2023
去年累计数 → 2022

PASS
```

```text
v5.7 old merge:
document_year = 本年累计数
year = 本年累计数 / 去年累计数

→ rematerialize

document_year = 2023
year = 2023 / 2022

PASS
```

```text
relative periods + unknown document_year
→ PERIOD_RESOLUTION_REQUIRED
→ blocked before canonical Merge

PASS
```

```text
spatial header token:
去年累计数
→ PRIOR

PASS
```

---

# 11. Retained functionality

v5.8 retains all v5.7 functionality:

```text
Relative-period table header extraction
Wrapped accounting row reconstruction
Blank-value detail preservation
Formula reconciliation
No-note-number body location
```

v5.6:

```text
Shared DATA_HOME
Migration Center
Conditional parent_section identity
```

v5.5/v5.4:

```text
Hierarchical header review
Header collision gate
Canonical structural order
Merge/Capture Library management
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
