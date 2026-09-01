# Regression Contract

A release must preserve all prior gates plus v6.1 architecture gates.

## Parser / table gates inherited from v5.9
- standard 4 columns must not become 8
- Classic / Generalized compatibility
- relative periods and wrapped labels
- BASE_MINUS_COMPONENTS reconciliation
- numeric-cluster referee
- topology KEEP/DROP safety
- absolute-year resolution

## v6.0 lifecycle gates
- batch grouping
- dependency impact
- bulk invalidation → stale Merge
- invalidated Capture merge gate
- lifecycle restore
- single-instance PID validation

## v6.0.1 gate
- Batch ID callback Session State contract

## v6.1 gates

```text
SQLITE_REGISTRY_BOOTSTRAP_PASS
HEADLESS_SERVICE_LAYER_PASS
SQL_FILTER_PAGINATION_PASS
BATCH_AGGREGATE_STATUS_PASS
SQL_DEPENDENCY_INDEX_PASS
SERVICE_INVALIDATE_DUAL_WRITE_PASS
SERVICE_REACTIVATE_DEPENDENCY_PASS
BATCH_ACTIVE_TRASH_SEPARATION_PASS
SERVICE_TRASH_RESTORE_PASS
PERSISTENT_JOB_REGISTRY_PASS
REGISTRY_REBUILD_FROM_DATA_HOME_PASS
HEADLESS_CAPTURE_REVIEW_MERGE_SERVICE_PASS
ALL_V61_BACKEND_ARCHITECTURE_TESTS_PASS
```

Run all:

```bat
run_regression_v61.bat
```
