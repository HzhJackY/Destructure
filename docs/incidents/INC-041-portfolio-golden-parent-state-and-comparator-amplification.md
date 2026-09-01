# INC-041：投资组合 Golden 父状态泄漏与比较器差异放大

- 状态：FIXED
- 日期：2026-08-23

## 现象

11 份投资组合 live 只读验收出现差异。旧比较结果把父路径/occurrence 连接失败扩散为大量
行字段 mismatch，无法清楚区分 Capture、Golden 和 comparator 责任。

## 根因

- Golden builder 的 active GROUP 状态没有在同级明细、TOTAL 或新分类段前可靠关闭；部分
  source Golden 也没有显式表达 GROUP 与 ROOT 的切换。
- 历史 live 平安、新华 Capture 保留旧父子边，未反映当前 Spatial Capture 行为。
- comparator 把未连接行逐字段展开，并把 `raw_label` 排版差异作为阻断，造成差异放大。

## 修复

- 对独立 PDF 已确认的父行补正 GROUP 身份，并用 `parent_row_order: null` 标记 ROOT boundary；
- 强化 sidecar builder/schema/validator 的父边、同范围和 source consistency 门禁；
- 比较器将 `raw_label` 设为非阻断 lineage audit，并将唯一语义身份差异压缩为一条事实；
- 不修改生产历史 Capture，在全新隔离 DATA_HOME 重新走正式链路。

## 验证与剩余状态

- 当前生产只读快照：太保 2023/2025、国寿 2023–2025 已 MATCH；平安三年与新华三年仍
  显示旧 Capture 的紧凑语义身份差异。
- 全新隔离复跑：11/11 Golden MATCH，正式作业全部成功，Canonical Long 和研究工作簿均
  生成；逐行标签、父项、row kind、期间值零差异，未触发 OCR。
- 全量非 E2E pytest：508/508 通过；未运行浏览器 E2E。
