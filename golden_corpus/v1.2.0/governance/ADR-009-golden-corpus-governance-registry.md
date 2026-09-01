# ADR-009 - Golden Corpus Governance Registry

Status: ACCEPTED

## Context

`golden_corpus/v1.1.0/filing_inventory.csv` historically mixed 12 canonical
four-company filings with an excluded ICBC-AXA candidate.  It could verify PDF
identity but could not reveal missing Anchor/Pattern/values, whether values
covered a primary or supplementary child table, whether a physical continuation
relation was adjudicated, or which release scope was blocked.

The corpus has also evolved from main-statement values to primary child-table
values and independently adjudicated supplementary schedules.  A title ending
in `续` is not a sufficient basis to merge those categories: China Life 2023
and New China Life 2025 each reset a material dimension and are independent
logical tables.

## Decision

The corpus retains four governance artifacts.

- `filing_inventory.csv` contains only 12 canonical targets and preserves the
  legacy identity columns for compatibility.
- `filing_exclusions.csv` owns every excluded candidate and its reason.
- `golden_coverage_registry.csv` owns the per-filing release summary.  It has
  separate statuses and counts for main-statement values, primary child tables,
  supplementary child tables and continuation segments, together with period
  coverage and separate scope release states.
- `golden_table_segment_registry.csv` owns the certified logical-table and
  physical-segment evidence.  It records stable table/segment IDs, page span,
  source asset, values and relation evidence.

Only a `CONTINUATION_SEGMENT` with a certified
`continuation_of_physical_segment_id` and relation evidence is a continuation.
`SUPPLEMENTARY_TABLE` is an independent logical table even when the source
title includes `续`.  The current backfill records zero certified true
continuation segments; that is an audit gap, not evidence that the PDFs have
no continuations.

The migration archives the old inventory before replacing it, creates a change
log entry and is verified by a read-only validator.  No current parser output,
Capture artifact or UI action can write either registry.

Golden value counts describe independently verified PDF SOURCE cells.  Repeated
raw labels such as two distinct `合计` rows remain separate assertions when
their physical row order differs.  Runtime derived rows cannot satisfy a
Golden SOURCE assertion: parity preserves their row/cell lineage separately by
runtime status (including `DERIVED_REJECTED_NON_BLOCKING` and
`SUPPRESSED_BY_EXPLICIT_TOTAL`) without excluding other SOURCE rows that share
the same mixed root/derived asset.

## Consequences

`PRIMARY_ONLY` may be release-clear where a primary child-table Golden exists;
`ALL_NOTE_TABLES` remains blocked unless supplementary and continuation
coverage has been adjudicated for that filing.  ACL-1.1.3 independently
verified the previously missing primary child-table Golden assets for Ping An
2025, CPIC 2024, and China Life 2025.  Consequently all 12 canonical filings
are now `PRIMARY_ONLY=CLEAR`; the three filings retain an explicit
`BLOCKED_PENDING_FULL_NOTE_AUDIT` state for unaudited supplementary/continuation
inventory rather than being silently released.

Existing software remains compatible with the legacy inventory columns.  A
future consumer that selects a logical table or continuation segment must use
the certified table/segment registry, never infer identity from a coverage
count or a “续” title.
