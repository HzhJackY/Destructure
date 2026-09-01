# INC-20260803：中国太保扫描主表 OCR Anchor 金额证据丢失

## 现象

中国太保 2023 年报 PDF 第 74 页已通过 OCR TSV 保留行与 BBox，但 Stage A 的金融投资 Anchor 对照仍显示 `REJECTED_OCR_WITHOUT_NATIVE_GEOMETRY`，导致 Golden gate 无法比较四个当前口径子项的金额。

## 根因

`CpicRowParser` 仅把空间结果用于标签/附注解析；`StatementFamilyResolver` 又在 OCR 分支中强制清空 `statement_amount_*` 并统一标记拒绝。空间列拓扑、金额 token 与期间表头之间的已知几何关系没有独立传递到 Anchor 层。此外，过早按 member 去重会让旧比较列的 FVTPL 行遮蔽当前交易性金融资产行。

## 修复

- `spatial_row_reconstruction.py` 从同一表头行聚类年份列，避免正文标题年份造成重叠列带。
- `CpicRowParser` 仅在金额 token 落入表头推导的期间列、且不在附注列时产生 `anchor_amount_observations`。
- Transition 页面在获得空间期间证据后，优先保留当前列非横线的同 member 行。
- Resolver 和 occurrence assembly 保存该独立字段；Golden 仅将其用于 Stage A 的独立对照。

## 不变性

`statement_amount_raw`、Capture、Canonical Long 和 Merge 均不接受这些 OCR Anchor 观察值。每条观察值保留 token bbox、header bbox、期间列和证据状态。

## 回归

`test_v611_cpic_spatial_anchor_observation.py` 与中国太保 2023 PDF 74 页隔离 canary。
