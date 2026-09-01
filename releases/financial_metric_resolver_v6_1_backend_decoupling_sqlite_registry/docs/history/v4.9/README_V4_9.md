# Financial Metric Resolver v4.9 — Cross-Page Context + Wide Unit Column

v4.9 corrects the wide-table unit design and implements cross-page continued-table context propagation.

## 1. Wide table contract: unit is a COLUMN

Final structure:

```text
metric                unit    中银三星 2021    中银三星 2022
净利润                元      134342343.93    7770000.14
核心偿付能力充足率     %       124.61          107.11
货币资金              元      222120234.32    320189719.12
```

Contract:

```text
column 1 = metric
column 2 = unit
column 3+ = company-year values
```

There are no synthetic `指标（单位）` rows.

This applies to:

```text
machine_wide.csv
adjudicated_wide.csv
batch_wide.csv
```

`batch_wide.csv` remains the FINAL adjudicated research view.

## 2. `*_wide_values_only.csv` removed

v4.9 no longer generates:

```text
machine_wide_values_only.csv
adjudicated_wide_values_only.csv
```

The wide table is already program-friendly because the unit is a normal column.

When refreshing an old v4.8 run directory, obsolete values-only CSVs are deleted.

Excel returns to five sheets:

```text
machine_long
machine_wide
adjudicated_long
adjudicated_wide
review_log
```

## 3. Mixed-unit safety

If one metric unexpectedly has incompatible normalized units across documents:

```text
A company -> %
B company -> 元
```

the wide-table unit becomes:

```text
REVIEW_REQUIRED[%|元]
```

rather than silently choosing one unit.

## 4. Cross-page table header propagation

Real annual reports frequently split one table across pages:

```text
PDF page 10:
项目            2025年度    2024年度
经营活动净现金流 100         90
                  ↓ page break

PDF page 11:
投资活动净现金流 80          70
筹资活动净现金流 60          50
```

Page 11 has no repeated period header.

v4.9 can inherit from page 10:

```text
2025年度 -> 80
2024年度 -> 70
```

and can also inherit:

```text
unit
table type
```

Example provenance:

```text
source_method =
pdfplumber_table+cross_page_header:p10

header_source_page = 10
context_inheritance_confidence = HIGH
```

## 5. Continuation safety

Context is NOT blindly inherited from every previous page.

Evidence includes:

```text
- immediately previous PDF page only
- continued-table marker, when present
- same / compatible table type
- similar numeric-column shape
- previous header count vs current numeric-column count
- compatible or missing unit
- rejection when current page has a new explicit table header
```

Inheritance requires multiple continuity signals.

A new table such as:

```text
page 20: 现金流量表
page 21: 利润表 + new 2025/2024 header
```

will NOT inherit the cash-flow header.

## 6. Fast Index automatically includes the predecessor context page

Even when:

```text
neighbor_radius = 0
```

a candidate page now also deep-parses its immediately preceding page as a context-only page.

Metadata distinguishes:

```text
candidate_pages
context_pages
selected_pages
```

This is needed because a metric may be on page N while its period/unit header exists only on page N-1.

## 7. Cache compatibility

Cross-page propagation is re-run AFTER combining:

```text
cached deep-page blocks
+
newly parsed deep-page blocks
```

Therefore this case works:

```text
page 10 -> old cache
page 11 -> newly parsed
```

The continuation relationship can still be reconstructed.

## 8. Human-review provenance

When a candidate inherits a cross-page header, human review shows:

```text
candidate page: 11
header source page: 10
```

Candidate tables also include:

```text
表头来源页
```

Warnings explicitly state that period/unit context came from a previous page.

## 9. Previous fixes retained

v4.9 retains all major v4.8/v4.7/v4.6 protections:

- percentage never converts to yuan
- verified L0 alias writeback
- Candidate Value Recovery Layer
- split label / numeric-row recovery
- same-page cross-block value recovery
- 产生 / 使用 cash-flow semantic families
- sign-semantics safety
- percentage-vs-monetary type guard
- shifted 2022/2021 period-column binding
- parallel per-PDF live progress
- optional OCR
- batch L2 DeepSeek/Gemini
- machine vs adjudicated results
- human review materializes into final tables
- company SHA-prefix cleanup
- one PDF / one company-year column identity

## 10. Validation performed

Regression tests passed:

```text
Cross-page continuation:
page 10 headers = 2025 / 2024
page 11 values  = 80 / 70
→ 80 -> 2025
→ 70 -> 2024
→ unit inherited = 百万元
PASS

New explicit table on next page:
→ no incorrect inheritance
PASS

Wide table:
metric | unit | company-year
PASS

No unit rows:
PASS

No *_wide_values_only.csv:
PASS

Excel sheets:
machine_long
machine_wide
adjudicated_long
adjudicated_wide
review_log
PASS

Mixed unit:
% + 元
→ REVIEW_REQUIRED[%|元]
PASS
```

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

or use:

```text
run_gui.bat
```
