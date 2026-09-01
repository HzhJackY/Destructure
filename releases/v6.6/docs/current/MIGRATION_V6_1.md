# Migration to v6.1

## From v6.0 / v6.0.1

No destructive migration is required.

The existing shared DATA_HOME remains in place.

First launch creates:

```text
DATA_HOME/metadata.db
```

Then an initial registry bootstrap indexes:
- PDFs
- Captures, including lifecycle metadata
- Batch aggregates
- Merge projects and source dependencies

Existing Capture/Merge files are not replaced.

## Rebuild / repair registry

GUI:

```text
系统与迁移 → Backend / Metadata Registry → Registry Full Sync
```

CLI:

```powershell
python service_cli.py sync-registry
```

Because SQLite is an index/control plane, deleting a corrupt `metadata.db` and performing a full sync is a supported recovery strategy. Back up DATA_HOME before manual filesystem operations.
