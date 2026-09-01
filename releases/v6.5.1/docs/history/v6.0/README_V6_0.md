# Financial Metric Resolver v6.0
## Data Asset Management Center + Batch Lifecycle + Single-Instance Launcher

v6.0 focuses on operational safety once the project contains many years, many insurers, and many historical extraction runs.

The core change is that historical asset management is no longer embedded inside the `整表抓取` page.

A new top-level workspace is added:

```text
数据资产管理
```

It centrally manages:

```text
Capture
Batch
Merge
PDF source evidence
Recycle Bin
```

v6.0 also introduces a safe single-instance launcher so opening a newer version does not silently leave an older Streamlit server running in the browser.

---

# 1. Capture lifecycle

Capture assets now have explicit lifecycle states:

```text
ACTIVE
INVALIDATED
TRASHED
```

## ACTIVE

Normal research asset.

```text
can be reviewed
can enter formal Merge when structural checks pass
```

## INVALIDATED

The extraction is known to be wrong or unusable, but machine evidence is preserved.

Typical reasons:

```text
PARSER_ERROR
HEADER_TOPOLOGY_ERROR
WRONG_TABLE_LOCATION
WRONG_BOUNDARY
WRONG_SOURCE_PDF
DUPLICATE_CAPTURE
TEST_RUN
OTHER
```

An invalidated Capture:

```text
remains auditable
remains visible in Data Asset Management
cannot enter canonical Merge
```

## TRASHED

The asset is moved to the recycle bin.

Typical use:

```text
duplicate test runs
debug captures
accidental uploads
assets no longer worth keeping in active history
```

Permanent deletion remains a separate explicit operation.

---

# 2. Bulk Capture management

`数据资产管理 → Captures` provides a spreadsheet-style asset table.

Filters include:

```text
lifecycle status
table name
company
document year
producer version
```

The interface supports:

```text
row selection
select all filtered results
bulk invalidate
bulk reactivate
bulk move to recycle bin
bulk re-capture from original PDFs
```

This is designed for cases where an entire extraction wave is later found to be wrong.

Example:

```text
Producer Version = v5.8
Table = 业务及管理费
Document Year = 2024

37 matching captures
→ Select all 37 filtered results
→ Bulk INVALIDATED
```

No one-by-one deletion is required.

---

# 3. Invalidation is preferred over deletion

A parser regression should normally be handled as:

```text
ACTIVE
↓
INVALIDATED
```

rather than:

```text
ACTIVE
↓
permanently deleted
```

The invalidation record stores:

```text
invalidated_at
invalidation_reason_code
invalidation_note
```

This preserves evidence for future parser audits.

Example:

```text
reason_code = HEADER_TOPOLOGY_ERROR
note = v5.8 generalized parser duplicated 4 real columns into 8 machine columns
```

---

# 4. Capture batch identity

New table captures can carry a shared:

```text
batch_id
```

The `整表抓取` page now has:

```text
整表抓取批次ID/标签
```

Example:

```text
2024年报_业务及管理费_第一批
```

Using the same batch ID for sequential captures makes them manageable as one logical extraction batch.

A button can generate a new ID automatically:

```text
TABLE_CAPTURE_BATCH_YYYYMMDDTHHMMSS
```

If no batch ID is supplied, the capture is treated as a singleton batch.

---

# 5. Batch management

`数据资产管理 → Batches` aggregates Captures by `batch_id`.

Each batch shows:

```text
capture_count
ACTIVE count
INVALIDATED count
TRASHED count
table_query
producer versions
created range
```

Supported batch operations:

```text
invalidate selected batches
re-run selected batches
move selected batches to recycle bin
```

This directly supports:

> “这一整批数据都抓错了，全部废除。”

---

# 6. Bulk re-capture and supersession chain

Selected Captures can be re-run from their original PDFs.

The re-capture creates a new batch and never overwrites the old Capture.

Metadata links the versions:

```text
old_capture
  superseded_by_capture_id

new_capture
  supersedes_capture_id
```

Typical flow:

```text
v5.8 Capture
↓ INVALIDATED
v6.0 replacement Capture
```

The original machine evidence remains available.

---

# 7. Merge dependency protection

Capture is a source asset.

Merge is a derived asset.

```text
Capture A
Capture B
Capture C
   ↓
Merge X
```

If `Capture B` is invalidated or trashed, v6.0 marks dependent Merge projects:

```text
STALE_SOURCE_INVALIDATED
```

Metadata records:

```text
dependency_status
stale_capture_run_ids
stale_reason
stale_at
```

This prevents an old Merge from continuing to look formally current after one of its source Captures has been rejected.

---

# 8. Formal Merge lifecycle gate

v6.0 adds a hard gate inside `table_merge.load_capture_long()`.

A Capture whose lifecycle is not:

```text
ACTIVE
```

cannot enter canonical Merge.

It raises:

```text
CAPTURE_LIFECYCLE_BLOCKED
```

This is independent of the GUI.

Therefore an invalidated Capture cannot accidentally enter a formal Merge through a lower-level workflow.

---

# 9. Merge dependency refresh

`数据资产管理 → Merges` includes:

```text
重新检查全部 Merge 依赖状态
```

The dependency scanner checks all manifest source Capture IDs.

Possible states:

```text
CURRENT
STALE_SOURCE_INVALIDATED
STALE_SOURCE_MISSING
```

If an invalidated Capture is deliberately reactivated and all dependencies are valid again, the status can return to:

```text
CURRENT
```

---

# 10. Historical management removed from `整表抓取`

`整表抓取` now focuses on:

```text
select PDF
configure target table
choose parser mode
run extraction
review current result
```

Historical lifecycle operations are moved to:

```text
数据资产管理
```

This avoids mixing:

```text
extraction workflow
```

with:

```text
historical database administration
```

---

# 11. Capture review still available centrally

Moving management out of `整表抓取` does not remove review functionality.

`数据资产管理 → Captures` includes a selected-Capture detail area with:

```text
Preview
Boundary Review
Header Parser Arbitration
Column Topology Review
Header Dimension Review
Total/Subtotal Reconciliation
```

The review workflow therefore remains available, but historical management is centralized.

---

# 12. Recycle Bin

`数据资产管理 → 回收站` contains:

```text
Capture Trash
Merge Trash
```

Supports batch:

```text
restore
permanent delete
```

Capture restoration preserves the pre-trash lifecycle when possible.

Example:

```text
INVALIDATED
↓ move to trash
TRASHED
↓ restore
INVALIDATED
```

It does not silently become ACTIVE.

---

# 13. PDF source asset view

`数据资产管理 → PDF` shows:

```text
filename
company
document year
file size
Capture reference count
Capture run IDs
```

v6.0 intentionally does not expose casual bulk hard deletion of source PDFs.

PDFs are source evidence and should generally be retained when referenced by historical Captures.

---

# 14. Single-Instance Launcher

The old startup:

```text
python -m streamlit run app.py
```

could leave an older version running on port 8501.

A new version might then open on another port or the browser might remain connected to the old server.

v6.0 changes the normal launcher to:

```text
run_gui.bat
→ launcher.py
→ Streamlit child process
```

The launcher maintains:

```text
DATA_HOME/runtime/active_instance.json
```

with:

```text
version
instance_token
launcher_pid
streamlit_pid
port
code_home
started_at
```

---

# 15. Safe shutdown of previous versions

When a new v6.0 launcher starts:

```text
check active_instance.json
↓
request graceful shutdown of previous launcher
↓
validate old Streamlit PID and command line
↓
close previous Financial Metric Resolver instance
↓
start new Streamlit
```

For older versions that were launched directly and have no instance registry, v6.0 can inspect the owner of the configured Streamlit port.

It only terminates the process if the command line is validated as:

```text
Streamlit
+ app.py
+ FinancialMetricResolver project marker
```

It never uses:

```text
taskkill python.exe
```

and does not terminate unrelated Python or Streamlit processes.

If port 8501 belongs to unrelated software, v6.0 leaves it untouched and selects another free port.

---

# 16. Restart / Exit buttons

The sidebar now includes:

```text
系统控制
├─ 重启程序
└─ 退出程序
```

These buttons do not call `os._exit()` from Streamlit.

Instead they write a token-authenticated control request:

```text
DATA_HOME/runtime/control.json
```

The launcher owns the child Streamlit process and performs the shutdown/restart.

This provides cleaner process ownership and avoids broad process termination.

---

# 17. Shared DATA_HOME remains the long-term storage contract

v6.0 continues using:

```text
DATA_HOME/
├─ uploads/
├─ table_captures/
│  └─ _trash/
├─ table_merges/
│  └─ _trash/
├─ config/
├─ runtime/
├─ asset_reports/
└─ ...
```

Upgrading from v5.9 does not require manually copying the old workspace.

Existing Captures receive lifecycle metadata lazily when first indexed by the asset manager.

---

# 18. v5.9 parser protections retained

v6.0 retains the entire v5.9 parser architecture:

```text
ABSOLUTE_YEAR_CLASSIC
GENERALIZED_PERIOD_V57
independent numeric-column referee
hard-rule arbitration
human parser selection
safe KEEP/DROP topology review
```

The permanent v5.9 regression corpus still passes.

---

# 19. v6.0 regression tests

Included:

```text
tests/regression_v59.py
tests/regression_v60.py
```

v6.0 lifecycle tests cover:

```text
BATCH_GROUPING_PASS
DEPENDENCY_IMPACT_PASS
BULK_INVALIDATE_AND_STALE_MERGE_PASS
INVALIDATED_MERGE_GATE_PASS
REACTIVATE_DEPENDENCY_REFRESH_PASS
TRASH_RESTORE_LIFECYCLE_PASS
SINGLE_INSTANCE_PID_VALIDATION_PASS
ALL_V60_ASSET_TESTS_PASS
```

v5.9 parser corpus also remains:

```text
ALL_V59_REGRESSION_CORPUS_PASS
```

---

# 20. Recommended upgrade workflow

For future use:

```text
1. Close the old manually launched server once.
2. Start v6.0 using run_gui.bat.
3. From then on, launch newer versions through their launcher.
4. Use 数据资产管理 for historical Capture/Batch/Merge administration.
5. Prefer INVALIDATED over permanent deletion for parser/data-quality failures.
```

## Launch

Windows:

```text
run_gui.bat
```

PowerShell:

```powershell
.\run_gui.ps1
```

Direct development mode remains possible:

```powershell
python -m streamlit run app.py
```

but direct mode does not provide full launcher-owned restart/exit semantics.
