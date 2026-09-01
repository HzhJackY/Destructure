# INC-032 — 认证列语义与物理表头几何脱节

状态：`RESOLVED_TARGETED_AND_REAL_PDF_VERIFIED`

## 现象

中国人寿 2023 投资组合 Whole-table Capture 成功，但把第二层表头“投资资产类别”物化为
第一条空值 DETAIL，导致后续真实资产行与 Golden 行序整体错位。

## 根因

`DIRECT_PORTFOLIO_TABLES` 的 `CERTIFIED_COLUMN_CONTEXT` fallback 根据四条数值 lane 和两个
期间直接合成“金额/占比/金额/占比”列语义，却把 `header_y1` 留在认证 ROI 顶部。通用
`_header_metadata` 能因期间文字延长到日期行，但其显式列标签补扫只处理 scope 与重述标记，
不会因普通“金额/占比”延长边界。列语义和物理表头范围因此使用了不同证据。

## P0 修复

- fallback 必须在认证 ROI 顶部、首个数值数据行之前找到两个真实期间；
- 必须找到与四条数值 lane 对齐的金额类/比例类物理叶表头；
- `header_y0/header_y1/data_y_min` 使用这些真实文字 bbox，不再使用合成标签伪造几何；
- 缺少物理表头证据时返回 `None`，由既有 header arbitration fail-closed；
- 不修改 ROI、物理底线 shadow、OCR、Golden 或 Stage A/B 身份门禁。

## 验证状态

- 合成核心回归：13/13；投资组合/认证列上下文套件：76/76；全部直接依赖空间 Capture 的
  非 E2E 回归：27/27。
- 中国人寿 2023 物理页 21：原生空间 Capture 13 行，首行为“固定到期日金融资产”，
  “投资资产类别”泄漏为 0；与认证 Golden 的 13 行标签、顺序和 52 个数值单元完全一致。
- 中国人寿 2024/2025 Direct 非退化：分别 26/22 行、四列、表头泄漏为 0。
- 三份真实 PDF 均未启用 OCR；未写生产 DATA_HOME、未重试用户作业、未运行浏览器 E2E。
