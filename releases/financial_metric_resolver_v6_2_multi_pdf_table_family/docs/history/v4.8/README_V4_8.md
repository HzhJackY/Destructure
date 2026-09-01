# Financial Metric Resolver v4.8 — Percent / L0 Alias / Wide Unit Rows

v4.8 is a correctness and output-contract patch on top of v4.7.

## 1. Percentage values can never be converted to yuan

Fixed failure:

```text
raw = 124.61%
unit_original = %
value_yuan = 1246100   # WRONG
```

Root cause:

The old extractor treated `%` like a missing cell-level unit and inherited the surrounding table unit such as `万元`.

v4.8 hard contract:

```text
124.61%
→ parsed_number = 124.61
→ unit_original = %
→ value_yuan = None
→ analysis value = 124.61
→ output unit = %
```

This applies to both:

- normal table extraction
- adjacent numeric-row Value Recovery

A hard invariant also blocks any future:

```text
unit_original == %
AND
value_yuan != None
```

from silently resolving.

## 2. Monetary `value` and `unit` are now dimensionally consistent

The batch analysis `value` field already prefers normalized yuan when available.

v4.8 therefore makes:

```text
value = value_yuan
unit = 元
original_unit = source PDF unit
```

Example:

```text
PDF raw:
18,000 百万元

Long output:
value = 18,000,000,000
unit = 元
original_unit = 百万元
```

Percentage:

```text
value = 124.61
unit = %
original_unit = %
```

This prevents the old inconsistent combination:

```text
value = 18,000,000,000
unit = 百万元
```

## 3. Human-review L0 strong-alias writeback is now verified

The checkbox:

```text
将本次查询名加入标准科目的 L0 强别名
```

now performs a full verified transaction:

```text
read actual rules_path
→ collision check
→ backup
→ atomic write
→ reload production RuleBook
→ normalize_metric(alias)
→ verify standard metric and kind
```

Success example:

```text
L0_ALIAS_WRITEBACK_VERIFIED：
'投资现金流净额' -> '投资活动产生的现金流量净额' (alias)
```

Failure:

```text
L0_ALIAS_WRITEBACK_FAILED
```

causes rollback to the backup.

The UI no longer treats “JSON file was written” as sufficient proof.

## 4. Wide CSV now contains unit rows

The existing orientation is preserved:

```text
metric as rows
company-year as columns
```

Because units vary by metric, a single global unit row is impossible.

v4.8 adds one unit row immediately after every metric value row:

```text
metric                    中银三星 2022
净利润                    7770000.14
净利润（单位）             元
核心偿付能力充足率          124.61
核心偿付能力充足率（单位）   %
```

This applies to:

```text
machine_wide.csv
adjudicated_wide.csv
batch_wide.csv
```

`batch_wide.csv` remains the final adjudicated research view.

## 5. Values-only wide tables are also preserved

For code / regression / modeling workflows that want numeric rows only:

```text
machine_wide_values_only.csv
adjudicated_wide_values_only.csv
```

The Excel workbook includes:

```text
machine_long
machine_wide
machine_wide_values
adjudicated_long
adjudicated_wide
adjudicated_wide_values
review_log
```

## 6. Long tables retain units

Long tables continue to contain unit fields and now distinguish:

```text
unit
original_unit
```

For adjudicated data:

```text
final_unit
final_original_unit
```

For machine audit:

```text
machine_unit
machine_original_unit
```

## 7. v4.7 functionality retained

v4.8 retains:

- Candidate Value Recovery Layer
- split label/value row recovery
- same-page cross-block recovery
- 2025/2024 and 2022/2021 period binding
- cash-flow 产生/使用 semantic families
- sign-semantics conflict guard
- percentage-vs-monetary type safety
- parallel per-PDF progress
- OCR optional modes
- batch L2 DeepSeek/Gemini
- human adjudication materialization
- final vs machine long/wide separation
- company/hash/year identity fixes
- batch review / reports / audit

## Validation performed

Regression tests passed for:

1. `124.61%` with surrounding table unit `万元`
   - parsed = 124.61
   - unit = %
   - value_yuan = None
2. L0 alias write -> reload -> `normalize_metric()` verification
3. wide value row + unit row output
4. values-only wide output
5. monetary normalized value / output unit consistency
6. v4.7 cash-flow split-row recovery regression

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
