# CHANGELOG v4.6

- Strip internal 12-char upload SHA prefix from company inference.
- Strip storage SHA prefix from user-facing PDF names.
- Repair old outputs where SHA prefix leaked into company names.
- Treat pandas NaN/NaT/None/blank as missing years.
- Ensure missing value_year falls back to document_year.
- Prevent one PDF from splitting into blank-year and explicit-year wide columns.
- Rebuilt Report & Audit GUI branches for single vs batch runs.
- Restored batch report tabs.
- Added batch report self-heal from batch_results.json.
- Added batch human-review fallback from audit.jsonl.
- Track active batch run in session state.
- Clean batch metadata display while retaining internal storage identity.
