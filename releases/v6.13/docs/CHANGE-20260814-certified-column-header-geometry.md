# Change Report：认证列上下文的物理表头几何

## 目标

修复 `DIRECT_PORTFOLIO_TABLES` fallback 只恢复四列语义、未恢复第二层表头物理下界的问题。

## 行为变化

- fallback 现在要求期间行和四个金额/比例叶标签均来自认证 ROI 内的真实文字 bbox；
- 数据起点位于完整叶表头之后；
- 缺少物理叶标签时 fail-closed，不再把 ROI 顶部当作可用表头边界。

## 不变项

投资组合拓扑、认证 ROI、Stage A/B、Capture 正式路径、Golden 只读语义、OCR 与数据库 schema
均不变。已冻结的 joint physical-bottom shadow 未读取、未执行、未修改。

## 验证

- 合成核心：13 passed；投资组合/认证上下文：76 passed；空间 Capture 直接依赖：27 passed。
- 国寿 2023：13 行，第一行为真实资产行，表头泄漏 0；Golden 13/13 行、52/52 数值单元
  完全一致。
- 国寿 2024/2025：分别 26/22 行、四列、表头泄漏 0。
- OCR、生产 DATA_HOME 写入、作业重试、Streamlit/browser E2E 均未运行。

## 已知非本变更风险

离线重建国寿 2024/2025 resolver 证据时，页级期间候选仍可能先命中表前叙述年份，再命中
当前期日期。该候选排序问题在本修复前已存在；本次只验证 Capture 表头边界与行序不退化，
没有顺手改变期间 resolver。
