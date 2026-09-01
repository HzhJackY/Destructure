# ADR-004 — No Single-Metric Final Delivery

Status: FROZEN

A prior delivery used repeated single-metric resolution and produced invalid values, including note references as amounts, wrong periods/pages, family-boundary violations, and no table lineage.

Single-metric resolution may support recall or diagnostics only.

Final delivery:

```text
CertifiedChildTableLink
→ Whole-table Capture
→ Canonical
→ Merge
→ User Research XLSX
```
