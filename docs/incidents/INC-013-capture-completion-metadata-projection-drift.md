# Incident Report INC-013: secondary child 完成态数据库与文件投影漂移

## 1. 事发现象 (Symptom)

中国人寿 2023 持有至到期投资第二个 child block 在权威 Registry 中已为
`READY / CONFIRMED_AUTO / merge_ready=true`，但 child 目录的 `capture_metadata.json`
仍显示 `UNASSESSED / PENDING_CAPTURE_COMPLETION / merge_ready=false`。

## 2. 根本原因分析 (Root Causes)

- `_create_legacy` 在 bundle graph 提交后先对 derived child 执行 `sync_capture_run`。
- 当时 `capture_versions` 尚未由 CaptureCompletionService 创建，bridge 按合同写入
  `UNASSESSED` 和 `PENDING_CAPTURE_COMPLETION`。
- 随后的权威 reducer 正确更新数据库，但没有把同一 DecisionResult 回投文件。
- 所有首次创建的 secondary child 均可能出现该文件投影陈旧；权威 DB 状态不受影响。

## 3. 正式修复

- `CaptureCompletionService.complete()` 在数据库事务成功后，将同一个不可变
  `DecisionResult` 单向投影到 capture 目录的 `capture_metadata.json`。
- 投影字段包括 boundary/header、quality/review、merge_ready/blockers、warnings、
  asset/certification 以及完整 `capture_decision` 审计载荷。
- 不调用 `capture_readiness` 或其他第二决策器；数据库仍是权威 source of truth。
- 文件采用同目录 staged replace，避免部分写入。

## 4. 验证结论 (Verification Results)

- 状态链集成测试覆盖 READY、REVIEW_REQUIRED、事务回滚不投影及 secondary child
  Registry/文件一致性。
- AST 合同测试确认 completion projection 不调用第二 readiness engine，也不写入
  `PENDING_CAPTURE_COMPLETION` 默认判断。
- 中国人寿 2023 最终正式复跑结果记录在本任务 Change Report。

## 5. 后续注意

- 投影写入失败不得反向改写已经提交的权威数据库决策；completion 返回独立
  `metadata_projection` 状态供运行审计。
