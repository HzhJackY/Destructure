# INC-20260817 — Direct 行尾脚注格式覆盖不完整

## 现象

Fresh Capture 与研究合表仍显示国寿 `债权型金融产品1`、太保
`债权投资计划注1` 等尾随脚注号；`raw_item` 与 `normalized_item` 相同，且没有
`footnote_markers` / `footnote_evidence`。

## 根因

2026-08-15 的名称身份修复只把 `(数字)` / `（数字）` 定义为数字脚注候选。Direct PDF
证据认证也复制了相同的括号限定，导致国寿裸上标数字与太保“注+上标数字”在检查真实
span 几何或同页编号注释之前即被跳过。此前测试和真实 PDF 验收仅覆盖括号格式。

## 修复

- 扩展既有共享候选正则，使括号数字、裸数字和“注+数字”进入同一个
  `normalize_item_label_with_evidence()`。
- `certify_direct_row_footnotes()` 复用该同一正则，不再维护第二份格式定义。
- 三类格式继续执行完全相同的证据门禁；无证据时保留原名称并进入
  `ROW_LABEL_FOOTNOTE_UNRESOLVED`。
- 不修改 `raw_item`，不在 Canonical、Merge 或 Excel 层临时删除尾号。

## 不变项

不修改 ROI、金额、期间、单位、分类轴、Golden、历史 Capture 或生产 DATA_HOME。

