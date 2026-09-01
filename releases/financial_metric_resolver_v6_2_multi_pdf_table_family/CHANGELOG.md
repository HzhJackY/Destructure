# Changelog

## v6.2 — Multi-PDF Table Family + Financial Structure Resolver

### 批量任务与表族
- 增加受控并发的多 PDF 整表抓取、持久化 Job 状态、失败隔离与 retry lineage。
- 增加 `TableFamily`：同一年度可独立抓取多个目标表，并判定 LEGACY_COMBINED / SPLIT_COMPONENTS / PARTIAL_COMPONENTS_REVIEW_REQUIRED 等结构版本。
- 每个批次保留 job manifest 和 schema variant summary，不拼接、不覆盖来源 Capture。

### 财务结构与合表安全
- 增加多证据行结构派生：显式 parent_section、row_level、顺序和小计/合计语义共同形成置信度；缩进/层级不是唯一规则。
- 导出 `row_path`、`parent_row_order`、`structure_confidence`、`structure_evidence`，防止不同父节点下的同名明细相互覆盖。
- 增加单位/四舍五入敏感的小计核对：`PASS` / `PASS_WITH_ROUNDING` / `WARNING`。
- 维度缺失 + 多物理列造成的多值结果改为 `REVIEW_REQUIRED_DIMENSION_AMBIGUITY` 警告；完全同键的不同数值仍为 `VALUE_CONFLICT` 阻断。

### 模板与 LLM 配置
- 增加历史结构模板存储、相似度检索和可替换 `StructurePredictor` 接口，为后续 ML 排序模型预留契约。
- 增加 `config/llm_config.example.yaml` 与本地加载器；本地密钥文件被 `.gitignore` 和交付打包排除。

## v6.1 — Backend Decoupling + SQLite Metadata Registry

### Backend architecture
- Added SQLite metadata control plane at `DATA_HOME/metadata.db`.
- Added `MetadataRegistry` with WAL mode, foreign keys, indexed Capture/Batch/Merge/Job tables.
- Added Repository Layer for Captures, Batches, Merges, PDFs, and Jobs.
- Added Service Layer for Capture, Review, Asset, Batch, Merge, PDF, Registry, and Jobs.
- Added `backend_context.py` dependency container with no Streamlit dependency.
- Added headless `service_cli.py`.

### Metadata registry
- First v6.1 launch bootstraps existing DATA_HOME into SQLite once.
- Registry is rebuildable from filesystem evidence.
- New Capture/review/merge write paths include best-effort registry synchronization hooks.
- Added manual full-sync from UI and CLI.

### Data Asset Management
- Capture asset list now uses SQL-backed filtering and pagination.
- Dependency impact uses indexed `merge_sources` rather than rescanning every Merge for each selection.
- Batch main list excludes fully trashed batches.
- Added Batch aggregate status and dedicated Batch Trash view.
- Lifecycle operations use Service Layer and dual-write to legacy metadata/evidence + SQLite index.

### Job foundation
- Added persistent jobs table and `JobService`.
- Status contract: `QUEUED / RUNNING / SUCCESS / REVIEW_REQUIRED / FAILED / CANCELLED`.
- Heavy multi-PDF worker orchestration remains scheduled for the next workflow release.

### Project cleanup
- Historical per-version README/CHANGELOG files moved from project root to `docs/history/<version>/`.
- Root now uses consolidated `README.md` + `CHANGELOG.md`.
- Current guides live in `docs/current/`.

### Preserved
- v5.7 relative-period/wrapped-row fixes.
- v5.8 absolute-year resolution.
- v5.9 Classic + Generalized dual-header arbitration and topology review.
- v6.0 asset lifecycle, batch invalidation, stale Merge protection, and single-instance launcher.
- v6.0.1 Batch ID callback hotfix.

## v6.0.1
- Fixed Streamlit Session State exception when generating a new Capture Batch ID.

## v6.0
- Added Data Asset Management Center.
- Added Capture lifecycle: ACTIVE / INVALIDATED / TRASHED.
- Added bulk invalidation, trash/restore, batch rerun, Merge dependency stale marking.
- Added single-instance launcher and graceful restart/exit control.

## v5.9
- Added Classic + v5.7 Generalized dual-header parsers.
- Added independent numeric-column referee and parser arbitration.
- Fixed 4-real-column → 8-machine-column header regression.
- Added manual parser selection and safe KEEP/DROP topology review.

Older detailed notes are archived under `docs/history/`.
# v6.2

- 新增 Multi-PDF Parallel Capture、Table Family Capture 与持久化 Batch Job 监控；
- 新增受控 Worker、失败隔离、可重试 FAILED 作业及批次审计汇总；
- 保持 v5.9 / v6.0 / v6.1 回归门槛，并新增 `regression_v62.py`。
