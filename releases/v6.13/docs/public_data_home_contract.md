# Public DATA_HOME contract

## Purpose

DATA_HOME stores runtime documents, evidence, metadata and derived research outputs outside the source tree. Public evaluation must use a newly created empty directory. Never point a public demo or test at a production or personal historical DATA_HOME.

Resolution order:

1. `FIN_METRIC_DATA_HOME` environment variable
2. user-level DATA_HOME pointer
3. `data_home.json` beside the application
4. the default user data directory

For reproducible evaluation, set `FIN_METRIC_DATA_HOME` explicitly and do not commit the pointer file.

## Version identities

| Identity | Current value | Meaning |
|---|---:|---|
| Application version | `v6.12` | Code/runtime identity from `version.APP_VERSION` |
| Metadata registry schema | `15` | SQLite control-plane schema |
| DATA_HOME layout schema | `6.10` | Persistent directory/manifest layout contract |

These values are intentionally independent. A v6.12 application opening a layout-schema-6.10 DATA_HOME is not a version mismatch. `data_manifest.json.created_by` records the application that first created the manifest; `last_opened_by` records the current application. Existing `created_by` values are preserved.

## Layout

```text
DATA_HOME/
├─ metadata.db
├─ uploads/
├─ runs/
├─ reviews/
├─ cache/
├─ batch_runs/
├─ table_captures/
├─ table_merges/
├─ archive/
├─ migration_reports/
├─ runtime/
├─ asset_reports/
├─ text_indexes/
├─ research_exports/
├─ config/
└─ data_manifest.json
```

`metadata.db` is a rebuildable control-plane registry, not the authoritative financial-data store. Evidence and derived artifacts remain in their governed files and directories.

## Public distribution rule

No DATA_HOME content is included by default. This includes uploaded PDFs, metadata databases, Capture evidence, reviews, caches, exports and user-edited rules. A synthetic fixture may be distributed only after its provenance, license and absence of real data are explicitly reviewed and it is added to the public allowlist.

Schema migration and rollback must never silently delete or rewrite source evidence. Older application code may ignore newer additive records; rollback is a code selection, not a DATA_HOME restore operation.
