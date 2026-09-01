# Golden Governance Audit - 2026-08-04

Scope: `golden_corpus/v1.1.0`, four companies, 2023-2025, consolidated
financial-investment family.

## Result

Identity governance now contains 12 canonical filings and one explicitly
excluded historical candidate.  The backfill reconciles to 47 certified table
segments: 41 `PRIMARY_TABLE` segments, 6 `SUPPLEMENTARY_TABLE` segments and 0
certified `CONTINUATION_SEGMENT` segments.  It records 794 child-table value
assertions: 446 current-period, 302 comparative-period and 46 explicitly
restated-period assertions.

The rows are projections of existing independently adjudicated YAML.  This
audit did not inspect a new PDF, create values, add geometry, or certify a
continuation relation.

## Confirmed Gaps

- 中国平安 2025: Anchor and Pattern are certified; main-statement values and
  primary child-table values are missing.  Both scope release states are
  blocked.
- 中国人寿 2025: the same main/primary child-table Golden gap is present.
- 中国太保 2024: main-statement values exist, but primary child-table Golden
  values are missing.
- No filing has a certified true continuation segment.  `ALL_NOTE_TABLES` is
  therefore blocked pending full-note/continuation adjudication even where
  `PRIMARY_ONLY` is clear.

## Classification Check

- 中国人寿 2023 has two `SUPPLEMENTARY_TABLE` schedules at pages 177 and 178.
  Their cost/fair-value and hierarchy dimensions reset; neither is represented
  as a continuation.
- 新华保险 2025 has four `SUPPLEMENTARY_TABLE` schedules at pages 195-197.
  Their year/stage dimensions reset; neither is represented as a continuation.

This preserves the certified fact that a “续” title is layout context, not a
continuation identity assertion.
