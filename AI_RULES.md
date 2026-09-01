# AXA_research Permanent AI Rules

## Rule 001 — No single-metric final-delivery path

`resolve_metric`, keyword search, nearest-number selection, and metric-by-metric PDF loops may support recall or diagnostics only.

Final research values must follow:

```text
CertifiedChildTableLink
→ Whole-table Capture
→ Canonical
→ Merge
→ User Research XLSX
```

## Rule 002 — No invented financial amounts

LLM and OCR may identify, rank, select bounded candidates, or abstain. They may not invent, repair, copy, interpolate, infer, or force amounts.

## Rule 003 — OCR amount isolation

OCR numeric tokens cannot directly populate the certified amount channel. Every amount must be linked to table data-column geometry, period header, unit, row label, PDF/page/bbox, and Capture lineage.

## Rule 004 — Financial-investment family boundary

Do not automatically include:

- 投资收益
- 长期股权投资
- 定期存款
- 所有者权益
- generic “投资” or “权益”

Only Research Definition-approved members enter the core family.

## Rule 005 — China Life has no fake parent

For implicit-member filings:

```text
resolution_mode = IMPLICIT_MEMBER_SET
raw_parent_label = null
```

Never synthesize a raw “金融投资” parent.

## Rule 006 — Human adjudication must be real

Do not write `HUMAN_CONFIRMED`, `CONFIRMED_OVERRIDE`, or equivalent unless reviewer, timestamp, reason, before/after, and source evidence exist.

## Rule 007 — No forced certification

Do not assign `CERTIFIED_ACTIVE`, `PASS`, or `MERGE_ELIGIBLE` from a Manifest, expected count, generated CSV, or script default.

## Rule 008 — Expected denominator is external

Expected members and required child tables come from Research Definition, certified Golden assertions, and audited human facts. Do not define expected from actual discovered results.

## Rule 009 — Whole-table Capture is mandatory

Required note details must preserve title, headers, periods, unit, all required rows, multi-block structure, multiple totals, and source provenance. A one-row metric result is not a table Capture.

Whole-table completeness is assessed within the user-selected, explicitly persisted Capture scope. `PRIMARY_ONLY` means complete within that limited scope; it must not be reported as the natural end of the full logical table in the PDF.

## Rule 010 — Multiple totals and blocks must be preserved

`TOTAL` does not automatically mean hard end. Preserve local/intermediate/final totals, whereof/memo blocks, listing-status blocks, and multiple classification axes.

Continuation and supplementary segments excluded by policy must remain in the segment manifest and boundary evidence. They must not be silently discarded or horizontally concatenated into another table.

## Rule 011 — UI is not a business-state engine

Opening a page, rendering a component, or calling `st.rerun()` must not create, fix, certify, or recompute business state.

Streamlit may display and collect a Capture scope choice, but only an explicit submission may persist it. Rendering and rerun must not mutate the submitted policy.

## Rule 012 — No duplicate production pipeline

Do not create a second OCR pipeline/cache, discovery resolver, Capture materializer, Review state machine, Canonical materializer, Merge engine, or user-export source.

## Rule 013 — Contract changes require ADR

Changes to family boundary, Capture/evidence schema, canonical identity, merge comparability, state derivation, or Golden blocking semantics require an ADR.

## Rule 014 — Every bug fix gets a regression invariant

A fix requires a targeted regression, affected real-PDF Canary when applicable, incident record, and Change Report.

## Rule 015 — Do not overwrite raw evidence

Machine evidence is immutable. Human adjudication is a separate layer. Certified output is derived from both.

## Rule 016 — Missing is not zero

Never replace missing, unresolved, not disclosed, not applicable, or incomparable observations with zero.

## Rule 017 — Reports do not prove completion

Markdown, CSV, XLSX, row counts, or status summaries do not prove completion without database facts, runtime evidence, artifacts, and lineage.
