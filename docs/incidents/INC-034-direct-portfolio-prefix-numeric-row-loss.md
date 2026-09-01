# INC-034 — Direct 投资组合首轴前数值行被标题清理删除

状态：`RESOLVED_TARGETED_AND_REAL_PDF_VERIFIED`

## 现象

新华保险 2023–2025 Direct 复合投资组合在物理 Capture 中均存在首行“投资资产”，但 UI
研究宽表只显示后续投资对象和会计计量行。既有 53 条分类数据与 246 个字段验收均匹配，
总览源行却完全缺失。

## 根因

`_axis_assignments()` 把首轴前行继承给第一个分类轴；随后
`_normalise_certified_direct_logical_axis_rows()` 找到轴标题后执行
`rows[heading_index + 1:]`，同时删除轴标题及其之前所有行。Resolver 与 Capture 还各自维护
固定 marker/alias，导致相同标题在 Discovery 与归一阶段可能产生不同语义。

## 修复

- 新增共享纯语义识别器，覆盖投资对象、会计计量词和多种 `按…` 边界结构；未知轴保留
  `UNRESOLVED`。
- 首个认证轴之前存在数值行时条件物化 `portfolio_summary / PORTFOLIO_SUMMARY`；无数值
  前缀时不生成、不阻断。
- 轴标题只删除自身；粘连数值行只剥离标题前缀。
- 增加 Direct 数值源行守恒门禁；page/bbox/source values 丢失或重复均 fail-closed。
- Registry 幂等增加可选总览成员；同一物理 link/作业/bundle 内物化三个逻辑 Capture，
  `portfolio_by_category` 继续作为 child_order=0 根。

## 验证边界

- 受影响定向回归 66/66（含 Registry 条件成员专项）。
- 隔离 DATA_HOME 重跑新华 2023–2025：3/3 成功，每年 1 个物理作业、3 个逻辑 Capture；
  总览各 1 行，分类数据 Golden MATCH，OCR=0，Canonical/Merge/XLSX 成功。
- 三份研究宽表中“投资组合（总览）”各出现一次，金额/占比与源 Capture 一致。
- 未写生产 DATA_HOME，未修改 Golden，未运行浏览器 E2E。
