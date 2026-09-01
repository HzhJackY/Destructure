# Change Report - Golden Governance Registry Migration

Date: 2026-08-04

## Changed

- Archived the previous 13-row filing inventory before producing the 12-row
  canonical baseline.
- Moved the ICBC-AXA non-target candidate into `filing_exclusions.csv`.
- Added filing coverage and table/segment registries, their JSON schemas and a
  read-only validator.
- Added ADR-009 and an audit report.  The annotation change log references
  `ACL-1.1.1-GOVERNANCE-MIGRATION`.

## Evidence and Validation

The registries only enumerate existing YAML assets.  The validator reconciles
inventory SHA/page counts, Anchor crops, YAML main-value counts, primary and
supplementary table assertion buckets, continuation relation invariants and
CSV aggregation.

## Residual Risk

The registry surfaces, rather than resolves, missing 2025/CPIC 2024 Golden
facts and the absence of certified true continuation segments.  Direct PDF
adjudication is still required before those statuses can be upgraded.
