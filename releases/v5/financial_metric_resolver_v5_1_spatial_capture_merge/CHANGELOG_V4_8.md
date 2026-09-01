# CHANGELOG v4.8

- Fixed percentage values inheriting surrounding monetary table units.
- Percentage values now always have `value_yuan=None`.
- Added hard `PERCENT_VALUE_YUAN_INVARIANT_VIOLATION` guard.
- Fixed batch `value` / `unit` dimensional consistency.
- Added `original_unit` to long output.
- Added `machine_original_unit` / `final_original_unit`.
- Added verified L0 alias writeback transaction.
- L0 alias writeback now performs production RuleBook reload + `normalize_metric()` verification.
- Alias verification failure rolls the rule file back.
- Wide tables now add a `指标（单位）` row after every metric row.
- Added `machine_wide_values_only.csv`.
- Added `adjudicated_wide_values_only.csv`.
- Added Excel sheets `machine_wide_values` and `adjudicated_wide_values`.
- Retains all v4.7 semantic/value-recovery and v4.6 identity/report/adjudication fixes.
