# Financial Metric Resolver v4.4 — Batch Safe Resolution

v4.4 is a correctness-focused patch on top of v4.3 Batch Fast Index.

## Fixed: L1 candidate found but value=None

Hard invariant:

```text
status = RESOLVED
        ⇒
primary_value != None
```

If the semantic row is found but no deterministic number is parsed:

```text
REVIEW_REQUIRED
```

The system is not allowed to publish `RESOLVED + None`.

## Fixed: 净利润 vs 本公司净利润 / 持续经营净利润

v4.3 lexical scoring added several signals together:

```text
string similarity
+ contains
+ keyword overlap
+ numeric/table bonuses
```

This could saturate a substring candidate at score `1.0`, tying an exact standard row.

v4.4 changes this to:

1. lexical evidence is non-additive;
2. exact standard > exact alias > soft alias > contains > fuzzy;
3. exact standard/alias row has strict semantic priority;
4. extra scope qualifiers are penalized:
   - 本公司
   - 母公司
   - 归母 / 归属于母公司
   - 持续经营 / 终止经营
   - 扣非
   - 少数股东
5. if an exact row exists but its number cannot be parsed, the system **does not fall through** to a qualified variant.

Example:

```text
净利润                  75,629,651.18
其中：持续经营净利润     75,629,651.18
本公司净利润             60,000,000
```

Query `净利润` must prefer the exact `净利润` row.

## Batch L2 restored

Batch GUI now has:

```text
Enable Batch L2
Provider: DeepSeek / Gemini
Model
API Key
```

L2 is only called when deterministic L1 cannot safely choose.

Safety contract is unchanged:

```text
LLM may select a bounded candidate ID or abstain.
LLM may not invent a financial value.
```

For API rate/cost control, use 1–2 workers initially when batch L2 is enabled.

## Batch human review restored

`人工复核` now supports:

```text
单 PDF 运行
批量运行
```

For batch runs you can select:

```text
batch run
→ document
→ metric
→ selected candidate / Top candidates
→ confirm / override / reject
→ save human_review.jsonl
```

The review UI shows:

- candidate ID
- page
- original label
- table type
- source method
- score
- whether numeric values exist
- match class
- extracted values
- snippet context

## Batch reports and audit restored

`报告与审计` now supports batch runs.

Each new batch run writes:

```text
batch_results.json
batch_long.csv
batch_wide.csv
batch_results.xlsx
batch_report.html
batch_report.md
audit.jsonl
human_review.jsonl   # after review
```

## Year fields

v4.4 keeps document year separate from value year:

```text
document_year
value_year
effective_year
year_source
value_period_raw
```

`value_year` is taken from the selected value's table/header context when available.
Only when it is unavailable does `effective_year` fall back to `document_year`.

This is safer than treating the PDF filename year as the value's actual period.

## Launch

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Important cache note

Because v4.4 changes candidate scoring and resolution rules, the raw PDF page cache remains reusable,
but old v4.3 final batch results should not be treated as re-certified v4.4 results.

Re-run the metrics to generate new v4.4 results.
