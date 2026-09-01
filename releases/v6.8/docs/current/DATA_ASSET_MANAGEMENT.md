# Data Asset Management — v6.1

## Capture lifecycle

```text
ACTIVE → INVALIDATED → TRASHED → PURGED
   ↑          │            │
   └──────────┘            └→ restore to pre-trash lifecycle
```

`INVALIDATED` is preferred for bad parser batches because evidence remains auditable.

## Batch views

Main **Batches** view excludes batches whose Captures are fully trashed.

Aggregate statuses include:
- `ACTIVE`
- `PARTIALLY_INVALIDATED`
- `FULLY_INVALIDATED`
- `*_WITH_TRASHED_ITEMS`
- `TRASHED`

Fully trashed batches are managed in:

```text
数据资产管理 → 回收站 → Batch Trash
```

This prevents ACTIVE and fully TRASHED batches from being visually mixed in the primary table.

## Merge dependency protection

When a source Capture is invalidated or trashed:

```text
Merge dependency_status = STALE_SOURCE_INVALIDATED
```

The underlying `merge_sources` relationship is indexed in SQLite for fast impact checks.

## Performance behavior

Capture management uses SQL filters and pagination instead of reading every Capture JSON on every Streamlit interaction.

The registry can be rebuilt at any time from filesystem evidence.
