# CHANGELOG v4.7

- Added Candidate Value Recovery Layer.
- Recover split label/value rows from adjacent numeric continuation rows.
- Recover values from same-page cross-block equivalent labels.
- Recover nearby equivalent label rows.
- Preserve period/header binding after recovered values.
- Added placeholder support (`-`, `—`, `不适用`, etc.) in continuation rows.
- Added cash-flow `产生` / `使用` canonical semantic aliases for operating/investing/financing.
- Added semantic-family metadata to cash-flow metrics.
- Updated DeepSeek/Gemini L2 prompts with cash-flow direction-wording semantics.
- Added L2 payload fields: has_values, value_count, recovery_evidence.
- Added value-type compatibility scoring.
- Added percentage-vs-monetary safety guard.
- Added cash-flow positive `使用` sign-semantics conflict guard.
- Never automatically flips cash-flow sign.
- Recovery evidence is preserved in candidate source_method / score_detail and human reports.
- Retains all v4.6 identity/year/review/report/adjudication fixes.
