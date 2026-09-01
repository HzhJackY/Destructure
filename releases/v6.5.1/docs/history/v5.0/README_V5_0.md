# Financial Metric Resolver v5.0 — Table Capture MVP

v5.0 adds a second extraction mode alongside single-metric resolution:

```text
单指标 / 批量指标
+
整表抓取
```

The goal is to capture a complete financial-note table faithfully before attempting cross-company semantic standardization.

## 1. New GUI workspace: 整表抓取

Sidebar now includes:

```text
总览
L0 指标字典
PDF 项目
运行提取
批量项目
整表抓取
人工复核
报告与审计
```

Typical input:

```text
目标表 / 附注名称:
业务及管理费和其他业务成本

附注编号:
34

最多连续抓取页数:
6
```

The engine:

```text
locates named note/table
→ bounds page range
→ deep parses tables
→ reuses cross-page continuation context
→ parses multi-level headers
→ extracts all detail / subtotal / total rows
→ preserves raw item labels
→ writes raw long / raw wide / item dictionary
```

## 2. Multi-level header parsing

Supported structure example:

```text
2025年度      2025年度      2024年度      2024年度
本集团        本公司        本集团        本公司
                            （已重述）     （已重述）
```

is materialized as four explicit column dimensions:

```text
2025 | 本集团 | restated=False
2025 | 本公司 | restated=False
2024 | 本集团 | restated=True
2024 | 本公司 | restated=True
```

The parser handles a common PDF failure where the blank left header cell is lost and header columns shift relative to data rows.

## 3. Complete detail-row capture

Rows are typed as:

```text
SECTION_HEADER
DETAIL
SUBTOTAL
TOTAL
CLASSIFICATION_TOTAL
```

Example:

```text
按费用项目：
→ SECTION_HEADER

手续费及佣金支出
→ DETAIL

职工工资及福利费
→ DETAIL

合计
→ TOTAL

可归属于保险合同组合的费用
→ CLASSIFICATION_TOTAL
```

The output retains:

```text
row_order
row_type
row_level
parent_section
```

so the original table hierarchy can be reconstructed.

## 4. Detail-item naming policy

v5.0 intentionally separates three concepts:

```text
raw_item
normalized_item
canonical_item
```

### raw_item

Exact source label, for example:

```text
保险保障基金(注)
```

### normalized_item

Deterministic text cleanup only:

```text
保险保障基金
```

Normalization may remove:

```text
(注)
（注1）
line breaks
spacing
full/half-width formatting noise
```

It does NOT merge economic concepts.

### canonical_item

v5.0 leaves this unmapped by default.

For example, it does NOT automatically assert:

```text
营销培训费
业务宣传费
广告宣传费
```

are the same accounting item.

Cross-company semantic taxonomy is a later adjudication layer.

## 5. Table outputs

Each capture run writes:

```text
table_capture_result.json
table_raw_long.csv
table_raw_wide.csv
table_item_dictionary.csv
table_report.md
table_report.html
table_capture.xlsx
```

### table_raw_long.csv

One row per:

```text
original detail item
×
table value column
```

Includes:

```text
raw_item
normalized_item
canonical_item
mapping_status

year
scope
restated
header_raw

value_raw
value
value_yuan
unit
original_unit

page
header_source_page
source_method
```

### table_raw_wide.csv

One row per original numeric item.

Example:

```text
row_order | row_type | parent_section | raw_item | normalized_item | unit
          | 2025 本集团 | 2025 本公司 | 2024 本集团 已重述 | 2024 本公司 已重述
```

### table_item_dictionary.csv

Mapping-ready item list:

```text
normalized_item
example_raw_item
canonical_item
category
mapping_status
mapping_note
```

`canonical_item` and `category` remain blank in v5.0 until a taxonomy/human mapping layer is applied.

## 6. Cross-page continued tables

v5.0 reuses the v4.9 Cross-Page Table Header Propagation layer.

A continuation page may inherit:

```text
period headers
unit
table type
```

while retaining provenance:

```text
header_source_page
source_method
```

This is important for financial-note tables spanning several PDF pages.

## 7. Table-location boundary

The locator searches the PDF text layer for:

```text
table name
+
optional note number
```

When a numeric note number is supplied, it also uses the next note number as a conservative page-boundary signal where possible.

A manual PDF start-page override is available when automatic location is ambiguous.

## 8. New L0 metric: 业务及管理费

Standard metric:

```text
业务及管理费
```

Strong aliases:

```text
业务及管理费用
业务管理费
```

Safety exclusions include table/detail-title concepts such as:

```text
业务及管理费和其他业务成本
其他业务成本
```

so the full note title is not automatically treated as the same single financial-statement metric.

## 9. New L0 metric: 支付给职工以及为职工支付的现金

Standard metric:

```text
支付给职工以及为职工支付的现金
```

Strong aliases:

```text
支付给职工及为职工支付的现金
支付给职工以及为职工支付现金
```

Important safety separation:

```text
职工工资及福利费
职工薪酬
应付职工薪酬
```

are NOT strong aliases.

They are different accounting concepts from the cash-flow-statement item.

## 10. v4.9 and earlier functionality retained

v5.0 retains:

- wide table `metric | unit | company-year...`
- no `*_wide_values_only.csv`
- cross-page table-header inheritance
- percentage never converts to yuan
- verified L0 alias writeback
- Candidate Value Recovery Layer
- split label/value recovery
- cash-flow 产生/使用 semantic family
- sign-semantics safety
- percentage-vs-monetary guard
- parallel batch progress
- optional OCR
- bounded-choice DeepSeek/Gemini L2
- machine vs adjudicated outputs
- human review materialization

## 11. Validation performed

Synthetic regression based on the provided 34-note table structure passed:

```text
2025 本集团
2025 本公司
2024 本集团 已重述
2024 本公司 已重述
```

Rows tested:

```text
手续费及佣金支出
职工工资及福利费
保险保障基金(注)
其他业务成本
其他费用
合计
可归属于保险合同组合的费用
```

Verified:

```text
multi-level header binding         PASS
restated-column binding            PASS
parent section "按费用项目"        PASS
footnote cleanup                   PASS
parentheses negative parsing       PASS
one-row-per-item wide output       PASS
cross-page provenance              PASS
Excel/CSV/JSON artifacts           PASS
```

L0 verified:

```text
业务及管理费用
→ 业务及管理费                   PASS

支付给职工及为职工支付的现金
→ 支付给职工以及为职工支付的现金 PASS

职工工资及福利费
≠ 支付给职工以及为职工支付的现金 PASS
```

## 12. Current MVP caveat

v5.0 deliberately prioritizes faithful raw capture.

It does not yet automatically force cross-company detail labels into one canonical taxonomy. That should be implemented as a separate bounded semantic-mapping / human-adjudication layer so raw source data can never be lost or silently merged.

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

or:

```text
run_gui.bat
```
