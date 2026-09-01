# INC-030 — 认证 ROI 解析/治理行归属语义分裂

状态：`RESOLVED_P0`

## 现象

中国人寿 2024、2025 投资组合 `DIRECT_COMPOUND_TABLE` 已正确认证同一物理表及两个逻辑
分类轴，空间解析也分别恢复 26、22 行，但作业在 Capture 持久化前被
`DIRECT_PORTFOLIO_RUNTIME_ROW_OUTSIDE_CERTIFIED_ROI` 阻断。

## 根因

- `spatial_table_capture._lines_in_roi` 对认证 bbox 使用矩形相交，末行字形框只要部分进入
  ROI 即被解析；
- `capture_service._validate_direct_portfolio_physical_manifest` 又要求整行 bbox 完全包含于
  ROI，仅允许 2 pt 容差；
- 两年的第二逻辑块末行字形框分别超出 ROI 3.476 pt、3.475 pt，但行中心明确位于 ROI 内。

该故障与末行是否叫“合计”无关，也不是 OCR、Stage A 身份或 Compound 分块失败。

## P0 修复

- 新增共享纯函数 `belongs_to_certified_roi`；
- 认证 ROI 的纵向行归属统一使用 bbox 中心，横向保持矩形相交；
- Capture 解析和 DIRECT_PORTFOLIO manifest 治理调用同一函数；
- 页面、标题、物理资产、分类、行页码及缺失 bbox 门禁保持不变；
- 不修改 Stage A 文本标记 ROI，不实现物理底线检测。

## 验证

- 合成/契约首轮：13/13；受影响回归：73/73；
- 国寿 2024 真实 PDF 内存重放：26 行，治理 `VALID`、issue 0；
- 国寿 2025：22 行，治理 `VALID`、issue 0；
- 国寿 2023 非回退：14 行，治理 `VALID`、issue 0；
- 三份均为原生空间解析，OCR 未使用。

未重试生产 Job，未写生产 DATA_HOME/Capture/Registry；浏览器 E2E、Canonical、Merge、
Golden 验收未运行。

