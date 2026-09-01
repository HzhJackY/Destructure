# v6.1 Architecture

## Target separation

```text
Transitional Streamlit UI
          │
          ▼
Service Layer
CaptureService / ReviewService / AssetService / BatchService / MergeService / JobService
          │
          ▼
Repository Layer
CaptureRepository / BatchRepository / MergeRepository / PdfRepository / JobRepository
          │
          ▼
SQLite Metadata Registry
DATA_HOME/metadata.db
          │
          ├───────────────┐
          ▼               ▼
Existing Python Core   Evidence/Data Files
PDF parser             PDF / JSON / CSV / Parquet
Table capture
Reconciliation
Merge / Taxonomy
```

The design intentionally does **not** rewrite the financial extraction core.

## Control plane vs data plane

### SQLite control plane
Stores:
- asset identity and paths
- company/year/table metadata
- Capture lifecycle
- Batch aggregates
- Merge dependencies and stale state
- persistent job state

### File data plane
Stores:
- source PDFs
- machine evidence JSON/CSV
- official reviewed outputs
- merge/canonical outputs
- taxonomy snapshots

SQLite may be deleted and rebuilt from DATA_HOME without deleting machine evidence.

## Repository contract

UI and future APIs should request metadata through repositories/services rather than directory scans.

Example:

```python
backend.capture_service.list(
    lifecycle_status="ACTIVE",
    document_year="2024",
    limit=100,
    offset=0,
)
```

## Service contract

Services are UI-independent. They may be called by:
- Streamlit v6.1 transitional UI
- `service_cli.py`
- tests
- future FastAPI endpoints

Asset lifecycle mutations follow:

```text
legacy evidence/file mutation
        ↓
registry synchronization
        ↓
Batch aggregate rebuild
        ↓
Merge dependency refresh when required
```

The filesystem remains authoritative if a registry update fails.

## Future transition

v6.1 is designed so future architecture can become:

```text
React + TypeScript
        ↓ REST/WebSocket
FastAPI
        ↓
Same v6.1 Service Layer
        ↓
Same repositories / SQLite / Python core
```

No parser rewrite should be required for the UI migration.
