# INC-004 — Parent/Child Line Index Mismatch

## Symptom

The first financial-investment child row was classified outside the family.

## Root cause

Parent and child functions computed `_line_index` values from different line spaces.

## Fix

Use one shared normalized line sequence.

## Permanent regression

Shared line space, blank-line perturbation, first-child inclusion, and stable evidence identity not based only on filtered line number.
