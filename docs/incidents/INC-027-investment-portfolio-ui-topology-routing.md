# INC-027 — 投资组合 UI 强制套用附注 Anchor/子表管线

状态：`RESOLVED_NODES_1_TO_6`

## 现象

太保集团 2023–2025 的 `INVESTMENT_PORTFOLIO_V2` Discovery 已找到
`DIRECT_COMPOUND_TABLE`，但 Guided UI 仍显示“主报表 occurrence 与附注候选”“认证所选
Anchor 并解析附注目标”，并可能保留切换 Definition 前的 V1 `NOTE_SECTION` 聚类，导致
用户无法确认直接物理表 Stage B 路径。

## 根因

- 离线 resolver 已具备拓扑证据，但 UI 没有消费共享的五拓扑执行计划；
- Stage A/Stage B 文案与渲染顺序以旧附注流程为默认；
- 切换 Definition/PDF/口径没有清理旧 session_state 的 Discovery/认证临时结果；
- 从“可选 Registry 知识包”选择投资组合时仍调用 V1 Family 的
  `DIRECT_NOTE_TABLE_FAMILY`，没有进入当前 `INVESTMENT_PORTFOLIO_V2`；
- Hybrid 缺少“Direct + Note 两分支均完成后才可 Capture”的显式完整性门禁。

## 修复

- 新增纯投影 `PORTFOLIO_TOPOLOGY_EXECUTION_PLAN_V1`，五类拓扑同时供 UI/离线使用；
- Direct、Note 认证目标显式分型，但继续物化为既有 `CertifiedChildTableLink`；
- Compound UI 显示一个物理 ROI 与两个 logical block，不再要求附注 Anchor；
- Hybrid 同一 filing 同时展示/校验两类目标，任一必需目标缺失则 fail-closed；
- Definition/PDF/口径切换时清理旧临时 UI 结果，不修改已持久化业务证据。
- 投资组合知识包的新任务强制路由到 ACTIVE/CURRENT 的 V2 Definition；V1 只保留历史身份。

## 节点 4–6 关闭结果

- 服务层现从持久化 occurrence 重建 plan；UI/离线均不能用不完整 links 绕过门禁；
- compound 认证链接保留两个 logical block/member/axis，但只执行一次物理 ROI Capture；
- 太保集团 2023 真实年报 native-text Canary 完成一个作业并物化两个逻辑 Capture：
  `BY_INVESTMENT_OBJECT` 与 `BY_ACCOUNTING_MEASUREMENT`；
- 修复“两个年份 × 金额/占比”四 lane 表头，以及带脚注行超出旧右边界的误报；
- 五拓扑服务合同及受影响回归 97/97 通过；浏览器 E2E、OCR、Canonical、Merge、XLSX 未运行。
