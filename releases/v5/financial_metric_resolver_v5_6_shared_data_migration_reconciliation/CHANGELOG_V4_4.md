# CHANGELOG v4.4

- Fixed `RESOLVED` results with `primary_value=None`.
- Added hard numeric invariant for batch output.
- Reworked lexical candidate scoring to prevent substring score saturation.
- Added strict exact-standard / exact-alias dominance.
- Added qualified-scope penalties for `本公司净利润`, `持续经营净利润`, etc.
- Exact label without number now blocks unsafe fallback to a different semantic variant.
- Restored optional L2 DeepSeek/Gemini in batch workers.
- Restored full resolution details in batch output.
- Added batch `audit.jsonl`.
- Added batch HTML / Markdown reports.
- Added batch human review support in GUI.
- Added batch Report & Audit support in GUI.
- Separated `document_year` and `value_year` in batch long data.
- Added `tabulate` dependency for Markdown batch report.
