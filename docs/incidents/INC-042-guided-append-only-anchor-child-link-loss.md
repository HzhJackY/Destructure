# INC-042：Guided append-only Anchor 重放丢失已认证子表

- 日期：2026-08-24
- 状态：RESOLVED
- 影响：`FINANCIAL_INVESTMENT_V1` FakeStreamlit/生产 Guided Stage B

## 现象

12 份年报已有 63 条正式 `CertifiedChildTableLink`（49 primary、14 supplementary），但
Guided 重放只生成 38 个 primary 请求；UI/Offline parity 为 6/12。既有 Capture Plan 还可能
因严格 ID 未包含 target inventory 而继续复用少项版本。

## 根因

Discovery 重放按 append-only 合同生成新的 occurrence ID，而认证链接归属旧的正式 Anchor
ID。UI 只按新 ID 查询链接，无法恢复同一物理 Anchor 的旧认证资产。与此同时，
`PLAN_STRICT` 未纳入 `certified_target_ids`，链接清单变化不一定产生新计划。

## 修复

1. repository 增加受正式 Anchor 审计约束的物理身份回退查询；匹配字段为 PDF、年度、口径、
   主表页、statement type、family、Research Definition 及版本。
2. Guided UI 合并 fresh 与 restored 链接，并按 `certified_link_id` 去重。
3. `PLAN_STRICT` 纳入排序后的认证 target ID 集合。
4. 已正式认证 Anchor 的机器可选几何门禁失败降级为审计 WARNING；未认证候选保持硬阻断。

## 验证

- Stage A：恢复 63 条链接，其中 49 primary、14 supplementary。
- 隔离 UI：49 个 primary 作业，12 批次终态，0 失败，UI/Offline 12/12 PASS。
- 生产：批次 `RB_d3461bf38d4445548cf3012e6b23f612`，49 作业，0 失败，数据库完整性 `ok`。
- 修复提示等级后：`ui_error_count=0`，8 条机器门禁信息为 WARNING。
- 全量测试：539/539 PASS；浏览器 E2E：`SKIPPED_BY_USER`。
