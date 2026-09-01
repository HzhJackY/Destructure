# INC-033 - Direct 认证列拓扑与边界合同不兼容

状态：`RESOLVED_TARGETED_AND_REAL_PDF_VERIFIED`

## 现象

新华保险 2024-2025 投资组合 Direct 复合表有五个数值 lane。旧
`CERTIFIED_COLUMN_CONTEXT` 固定四 lane，AUTO 表头仲裁把五 lane 压成两列，Capture 在
表头阶段失败。

## 根因

- 认证列上下文混合了固定四 lane 业务假设和物理列证据。
- 复合块规范化用展示标题匹配物理轴标题，导致“投资资产”及“按投资对象
  分类”泄漏成数据行。
- Direct ROI 验证器输出 `DIRECT_PORTFOLIO_PHYSICAL_ROI`，边界裁判器却只接受
  普通附注的七项 pair schema，已认证 ROI 被误判为 `PDF_BOUNDARY_UNCERTAIN`。
- 验收 runner 把 bundle 子 Capture 直接传入 Merge，违反“只传根 Capture”合同。

## 修复

- 持久化并严格消费 N-lane V2 `period/header/amount_lane` 三类签名。
- AUTO 仅在 lane 数冲突时让完整认证拓扑接管；`PERIOD_CHANGE` 列允许 `year=None`。
- 复合块使用认证 `classification_axis` 的受控标题集去除物理总标题/轴标题。
- 边界裁判器显式支持 Direct ROI 验证模式，仍对 segment 身份、manifest、行归属和
  drift 全部 fail-closed。
- 验收 runner 按 bundle graph 将子 Capture 折叠到 `child_order=0` 根 Capture 后再 Merge。

## 验证边界

- 最终受影响回归：70 passed。
- 全新隔离 `DATA_HOME` 真实 PDF 全链：新华 2024、新华 2025、国寿 2023 共 3/3 通过。
- 新华两年均为类别块 13 行 + 计量块 5 行，Golden MATCH、两子块 `merge_ready=1`。
- 三案 OCR=0，Canonical Long 和两份研究 XLSX 均生成。未写生产 `DATA_HOME`，未运行浏览器 E2E。
