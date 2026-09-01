# INC-001 — Single-Metric Fake Delivery

## Symptom

A rapid task generated a 72-row workbook and claimed complete research delivery.

## Root cause

Single-metric resolution was used instead of whole-table Capture, and nearby numeric tokens were treated as financial values.

## Impact

Note references became amounts, pages/periods were wrong, non-family metrics were included, and lineage was absent.

## Permanent controls

ADR-004, AI Rule 001, independent shortcut detection, and PDF→Capture→Canonical→Merge→XLSX lineage.
