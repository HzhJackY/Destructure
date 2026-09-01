# CHANGE — 投资组合直接披露完整离线管线

日期：2026-08-13

状态：`PING_AN_OFFLINE_BASELINE_ACCEPTED`

## 变更范围

- 在既有 Generic Discovery 内增加 `DIRECT_PORTFOLIO_TABLES` Resolver。
- 增加 `INVESTMENT_PORTFOLIO_V2`，保留 V1 历史身份且默认隐藏。
- 将 Stage A Golden 与 Stage B 物理表认证按 Registry Family 隔离。
- 直接投资组合表使用认证 ROI、页码、标题、物理资产 ID 和原生单位证据；不执行
  金融投资附注检索，不放宽金融投资的 Stage A/B 门禁。
- 在原 Capture 结果内恢复原生文本明确存在的分组行和缩进父子关系，禁止 Golden 回填。
- 逐行 Golden 升级为 v2，共 10 份年报、209 行。

## 验证

- 真实 Discovery/Stage A 矩阵：10/10 MATCH，OCR 0。
- 平安 2023 全链：Stage A 1.00；两张物理表、两条认证链接；两 Capture SUCCESS；
  30 行逐行 Golden MATCH；Canonical Long、Merge 与两份研究 Excel 均生成。
- 定向与受影响 pytest：24 + 65 通过。
- 两份 Excel 均可导入；14 个工作表逐表渲染，公式错误扫描 0；研究宽表目视可读，
  Merge 值冲突与顺序冲突均为 0。Reconciliation 中的父子平铺和为审计 WARNING，按
  既有 ADR-007 不阻断 Merge。

## 未运行

- 按用户指令未运行浏览器 E2E。
- 未运行 OCR；样本均为原生文本。
- 未执行附注组件/混合拓扑的正向真实年报管线。
