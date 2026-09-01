# Financial Metric Resolver v6.2

## v6.2：批量抓取与财务结构理解

- 多 PDF：一次选择多份 PDF；每个 PDF × 目标表创建独立、持久化 Job；默认 3 个 Worker，最多 8 个。
- 表族：内置“投资相关收益”（投资净收益 / 投资收益 / 利息收入），支持自定义多表、角色和 schema variant 判定。
- 失败隔离：单个 PDF 或表未匹配不会中断同批任务；`FAILED` 可安全创建新的 retry Job，原 Job 保留审计记录。
- 结构层：新增可审核的 `row_path`、父行、置信度与证据；重复行名只要父路径不同即不会静默冲突。
- 核对层：小计/会计等式核对采用金额单位和显示四舍五入容差，输出 `PASS` / `PASS_WITH_ROUNDING` / `WARNING`，不会篡改来源值。
- 合表层：维度缺失导致的多列歧义标记为 `REVIEW_REQUIRED_DIMENSION_AMBIGUITY`（警告）；完全相同经济键的不同数值仍是阻断性 `VALUE_CONFLICT`。
- 模板层：保存历史结构模板并作相似度检索；`StructurePredictor` 是后续 embedding/LightGBM 模型的稳定替换接口。
- LLM：可选本地 `config/llm_config.yaml`；密钥不写入 SQLite、审计文件、版本控制或项目包。

### 审计边界

`table_capture_result.json` 与既有 machine evidence 不会被 v6.2 结构层回写。行路径、结构置信度、结构审计是从导出的长表确定性派生的附加字段；人工复核仍是任何低置信结论进入研究层之前的唯一授权路径。

PDF-first financial / insurance statement extraction workbench.

v6.1 is an **architecture foundation release**. It keeps the existing audited PDF parsing, table capture, review, lifecycle, and merge behavior, while separating metadata/business operations from the Streamlit UI.

## What changed in v6.1

- Added `DATA_HOME/metadata.db` as a rebuildable **SQLite Metadata Registry**.
- Added Repository Layer: `repositories/`.
- Added Service Layer: `services/`.
- Added `backend_context.py` dependency container shared by UI, CLI, tests, and future FastAPI.
- Added persistent Job Registry schema and `JobService`.
- Added headless `service_cli.py`.
- Data Asset Management now queries SQLite rather than rescanning all Capture/Merge folders on every interaction.
- Capture list supports SQL filtering + pagination.
- Batch main view separates normal batches from fully trashed batches.
- Recycle Bin has a dedicated **Batch Trash** view.
- Historical README/CHANGELOG files moved to `docs/history/`; project root now keeps only current entry documents.

## Data contract

SQLite is the **control plane**, not the financial-data store.

```text
DATA_HOME/
├─ metadata.db              # metadata / lifecycle / dependencies / jobs
├─ uploads/                 # source PDF evidence
├─ table_captures/          # immutable machine evidence + official outputs
├─ table_merges/            # merge projects
├─ batch_runs/
├─ reviews/
└─ ...
```

Large or auditable data stays in PDF / JSON / CSV / Parquet. `metadata.db` can be rebuilt from `DATA_HOME`.

## Launch

Recommended:

```bat
run_gui.bat
```

The v6.1 single-instance launcher safely manages the Streamlit process without killing unrelated Python processes.

Manual launch:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Headless service API

The backend can be used without Streamlit:

```powershell
python service_cli.py registry-stats
python service_cli.py sync-registry
python service_cli.py list-captures --limit 50
python service_cli.py list-batches
```

Programmatic entry point:

```python
from data_home import resolve_data_home, ensure_data_home
from backend_context import build_backend_services

paths = ensure_data_home(data_home, bundled_rules)
backend = build_backend_services(paths)
backend.registry_service.bootstrap_if_needed()

captures = backend.capture_service.list(limit=100)
```

Headless service façades exist for:

- Capture creation / listing / registration
- Review adjudication
- Asset lifecycle operations
- Batch lifecycle operations
- Merge creation / refresh / lifecycle
- PDF metadata lookup
- Persistent Job Registry

## Migration from v6.0 / v6.0.1

No manual data migration is required.

On first v6.1 launch:

1. `metadata.db` is created.
2. Existing PDFs, Captures, Batches, and Merges are scanned once.
3. Metadata is indexed into SQLite.
4. Existing machine evidence is not rewritten.

A registry full-sync can be run from **系统与迁移** or:

```powershell
python service_cli.py sync-registry
```

## Regression gates

Run the full v6.2 chain:

```bat
run_regression_v62.bat
```

This executes v5.9, v6.0, v6.0.1, and v6.1 regression suites.

Current v6.1 architecture gates include:

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

## Documentation

Current documentation: `docs/current/`

Historical version documentation: `docs/history/`

See also:

- `docs/current/ARCHITECTURE_V6_1.md`
- `docs/current/DATA_ASSET_MANAGEMENT.md`
- `docs/current/MIGRATION_V6_1.md`
- `docs/current/REGRESSION_CONTRACT.md`
