# Incident Report INC-011: 新华年报侧页印刷页码（“07”）污染

## 1. 事发现象 (Symptom)

新华保险 2023 年报交易性金融资产附注（PDF 第 187 页）抓取中，右侧边距的印刷
页码“07”（x≈573–585，页中 y≈557）被识别为 `IMPLICIT_ROW_CANDIDATE` 单格行，
进入机器输出：显示为无标签假数值行；在双列表（两年列）中还会触发
`HEADER_TOPOLOGY_AMBIGUOUS` / `VALUE_COLUMN_COUNT_MISMATCH`。

## 2. 根本原因分析 (Root Causes)

- 既有 `_mark_tail_page_number_noise` 只处理“终止合计之后 + 页面底部”的
  尾页页码（如太保“85”）；新华“07”是页中、侧边距页码，两个条件都不满足。
- 分类缺少“侧边距 + 表格 x 带之外”这一空间维度。

## 3. 正式修复

- 新增 `_mark_side_page_number_noise`：无标签 + 单短整数 + 左侧/右侧边距
  （x1≤40 或 x0≥页宽−40）+ 位于表格 x 带之外 + 与印刷页码匹配 →
  标记 `PAGE_NUMBER_NOISE` + `excluded_from_table_logic=true`；
  原始行保留。
- 与尾页页码分类互补，按顺序执行；拓扑/列数复核/合表输出均排除。

## 4. 验证结论 (Verification Results)

- 新回归 5/5（标记/页码不匹配/表带内不标/带标签不标/双列拓扑排除）；
  相关既有 77 passed / 2 skipped。
- 新华 2023 交易性金融资产重跑：`07` 标记为 PAGE_NUMBER_NOISE，
  long/wide 输出剔除该行，拓扑一致，边界 SOFT_BOUNDARY_CONFIRMED，
  无 PDF_BOUNDARY_UNCERTAIN / HEADER_TOPOLOGY_AMBIGUOUS / VALUE_COLUMN_COUNT_MISMATCH。

## 5. 后续注意

- 新华 2024/2025 若存在同类侧页页码（双列表），本修复同样适用。
