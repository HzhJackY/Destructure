# v6.13 Machine Discovery 证据版本修复 Change Report

日期：2026-08-15

状态：`IMPLEMENTED_REAL_PDF_VERIFIED_NO_BROWSER_E2E`

## 变更目的

修复 Guided UI 重跑 Direct 投资组合 Discovery 时，稳定候选 ID 与变化后的置信度、候选页
和 evidence JSON 共用同一 SQLite 主键，导致 `MACHINE_DISCOVERY_IDENTITY_CONFLICT` 阻断的
问题。

## 实现

- `DiscoveryRegistry.save_machine()` 继续对完全相同证据幂等，对稳定身份冲突 fail-closed。
- 同一稳定候选仅机器证据变化时，不更新旧行，而是追加确定性的
  `<base_discovery_id>__R<sha256>` 证据版本。
- Guided UI 将 Registry 返回的实际版本 ID 写回 candidate，并用于构造后续 occurrence。
- 未新增数据库表或迁移；既有 `machine_discoveries` 行保持不变。

## 验证

- `tests/test_v613_guided_discovery_idempotency.py`：4 passed。
- Guided Discovery、投资组合拓扑、名称身份/多单位组合回归：23 passed / 1 failed。
- 唯一失败为既有拓扑 Resolver 测试缺少 `selected_topology`，与本变更无调用路径交集。
- 新华保险 2025 真实 PDF 隔离重放通过：旧 base 快照保留，当前证据追加一个确定性 revision，
  再次重放命中同一 revision；主表页 43、`DIRECT_COMPOUND_TABLE`、OCR 0。
- 浏览器 E2E 未运行；生产 DATA_HOME 仅只读核查，未写入。

## 回滚

回退 `discovery_registry.py`、`guided_workflow_ui.py`、测试和合同文档即可。修复只会追加不可变
机器证据版本，没有历史行覆盖或 schema migration，不需要数据库回滚。
