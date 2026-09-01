# v6.13 父期间与多行叶子列组修复报告

## 变更

- 将父期间从单点扩展为 V3 连续列组上下文，保存日期 anchor、列组 bbox、父/子表头行带、
  consumed spans、group ID 与审计证据。
- 同行结构采用左侧父期间优先、右侧惩罚回退；两行及多行结构按相邻期间和物理 leaf lane
  建立连续列组，再映射金额、占比和增减率。
- 叶子表头只消费父期间识别后的残余 spans；日期或日期残片不得成为 measure。
- 完整中文日期支持跨最多五个原生 word；半日期 `2024年12` 不再因脚注清理被错误认证。
- Capture Service 与 Orchestrator 保留认证 classification axis 对应的稳定 member identity。
- 共享轴识别器补充 `投资组合（按投资品种）` 等括号闭合标题，不放宽未知轴审核规则。

## 保持不变

- 不修改 ROI、认证 BBox、物理作业数量、五拓扑路由或历史 Capture。
- 不恢复“期间总额必须存在”门禁，不改写 Golden 金额或生产 DATA_HOME。
- 继续走唯一正式链：Whole-table Capture → CaptureDecisionReducer → Canonical Long → Merge → XLSX。

## 验证

- 四词日期、同行左右候选、多行连续列组、日期残片和 V3 metadata 定向测试 22/22。
- v6.13 全部定向测试 96/96；共享受影响回归 127/127。
- 隔离真实 PDF 父期间合同审计 6/6：太保 2023–2025、国寿 2024–2025、新华 2023 均无
  日期残片、identity 冲突、member 漂移、`PERIOD_COLUMN_SWAP_RISK` 或 merge blocker。
- 太保三年隔离 Canonical/Merge 3/3 成功，每年生成 Canonical Long 与两份 XLSX。
- 太保 Golden 标签/续行差异未纳入本修复，不放宽验收门禁；浏览器 E2E 按要求跳过。

## 回退

回退 `spatial_table_capture.py` 的 V3 period-group/日期 span 消费、Capture member 传播、
Orchestrator member 保留及对应语义标题兼容改动即可。无数据库迁移，历史 Capture 不需回滚。
