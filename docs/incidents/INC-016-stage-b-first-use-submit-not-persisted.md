# INC-016 — Stage B 首次“确认逻辑表并抓取”未持久化即失败

## 现象

- 全新会话（数据库无该 Stage B execution session 行）首次进入 Stage B 面板，
  预览显示“Capture Plan（数据库真源）”为只读计划，点击“确认逻辑表并抓取”后
  无法原子落库执行；服务层在 `persist_capture_scope` 抛出
  `KeyError: STAGE_B_EXECUTION_SESSION_NOT_FOUND:<session_key>`。
- 用户此前在兼容流程也观察到 `PermissionError:
  CAPTURE_SCOPE_IMMUTABLE_AFTER_SUBMISSION`，属于同一类“渲染与提交职责分离后，
  提交入口未带同源 inventory”的残留。

## 根因

- Stage B 面板按规则 011 改为只读预览（`preview_capture_plans(persist=False)`），
  不再在渲染阶段写库——这一步正确。
- 但“确认逻辑表并抓取”按钮调用 `create_execution_batch` 时只传
  `session_key` + scope 选择，没有把预览所用的 `certified_links` /
  `source_pdf_map` / `plans` 回传。
- 首次使用时没有既有 session 行，`create_execution_batch` 落入
  `persist_capture_scope`，直接以 `STAGE_B_EXECUTION_SESSION_NOT_FOUND` 失败；
  离线管道“候选 inventory → 认证 → 显式提交原子落库”的契约在 UI 侧断开。

## 修复

- 面板按钮把同一份 certified inventory/plan（`certified_links`、
  `source_pdf_map`、`plans`）随 scope 选择一起传给
  `create_execution_batch`；服务层既有分支
  `prepare_capture_plans(persist=True)` 完成计划、session 与 scope 的一次性持久化
  后再执行，与离线管道一致。
- 已恢复的既有 session（DB 已有 plan_ids）仍按 `session_key` 幂等提交，不受影响。
- Stage B 面板复选框改用共享展示词汇（附注主明细表 / 附注补充分析表），
  持久化枚举 token 不变。

## 回归

- 面板源码不变式：提交调用必须回传 `certified_links` / `source_pdf_map` /
  `plans`。
- service 级首次使用原子落库用例：`test_both_entry_adapters_use_same_persisted_plan_callback_and_lineage`。
- 展示词汇用例：`test_v611_presentation_labels.py`。

## 边界

- 未删除兼容流程入口；兼容计划同样经同一面板与同一回调执行。
- 未修改 `create_execution_batch` 服务合同、数据库 schema 或 Capture/Merge。
- 浏览器 E2E 仍按用户约定暂停。
