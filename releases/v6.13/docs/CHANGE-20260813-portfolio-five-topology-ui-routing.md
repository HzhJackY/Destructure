# CHANGE — 投资组合五拓扑 UI/离线共享执行计划（节点 1–6）

日期：2026-08-13

状态：`NODES_1_TO_6_COMPLETE`

## 变更

- `INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT_V2` 为五种拓扑补齐机器可读执行政策。
- 新增无副作用 `PortfolioTopologyExecutionPlan`，由 UI 与离线调用方共同消费。
- Guided UI 按 Direct、Note、Hybrid 路由显示 Stage A/B；Compound 不再伪装成附注表。
- Hybrid 要求 direct 与 note 两类必需认证同时闭合，并禁止 note 重复计入 direct 总额。
- 切换 Definition、PDF 或口径时清除旧 session 临时结果，避免 V1 聚类冒充 V2 当前结果。
- 从“可选 Registry 知识包”选择投资组合时，新任务也强制进入
  `INVESTMENT_PORTFOLIO_V2`，不再落入 V1 `NOTE_SECTION` 策略。
- 数据库 schema、既有金融投资认证、Capture/Canonical/Merge 主干均未分叉。

## 节点 4–6

- `ChildCaptureExecutionService` 重建持久化 plan，使离线与 UI 使用同一门禁。
- Direct compound 的一条物理认证链接保留全部逻辑成员、block、axis 与 period evidence。
- 复用原 Capture/compound segmentation：一个物理作业物化两个逻辑 Capture，不重复抓 ROI。
- 四数值 lane 仅在 certified direct-portfolio ROI + 两个明确期间下启用。
- 太保脚注标签行允许延伸到页面右边缘，垂直边界仍由认证 ROI 锁定。

## 验证边界

- 五拓扑 synthetic/service acceptance 与受影响回归：97/97。
- 太保集团 2023 真实 PDF native-text Capture Canary：1 个物理作业、2 个逻辑 Capture，PASS。
- 未运行浏览器 E2E、OCR、Canonical、Merge 或 XLSX。
