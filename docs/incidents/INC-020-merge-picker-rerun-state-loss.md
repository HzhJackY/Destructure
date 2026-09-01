# INC-020 — 合表筛选在下游控件重跑时丢失状态

## 现象

合表创建区按公司、年份、附注表名或研究批次筛选并选择 Capture 后，修改
`Canonical Table ID`、合表排序策略或基准年份等下游控件，会触发 Streamlit 全量重跑；
页面回到顶部，同时筛选条件和已选 Capture 被清空。

## 根因

新增筛选 picker 把条件渲染的 widget key 当作状态来源，并为可见 Capture 多选框使用
随筛选结果变化的动态 key。筛选值和选择值没有独立的持久状态模型，也没有在 widget
回调阶段同步，因此任何下游控件触发的 rerun 都可能受 Streamlit widget 生命周期清理影响。
排序与 Canonical Table ID 控件只是触发器，不是清空状态的业务逻辑。

## 修复

- 新增独立的 `v611_merge_assets_state`，持久保存筛选模式、各筛选值和 selected IDs。
- widget 首次或重新渲染时从持久状态恢复；失效的 Capture ID 和筛选选项按当前资格集合清理。
- 筛选、多选、全选与清空在回调阶段先同步持久状态，再执行页面 rerun。
- 保留原 `v611_merge_assets_selected_ids` 兼容键，不修改合表排序、Capture 或 Merge 数据合同。

## 回归

- 覆盖条件 widget key 被清理后，持久筛选模式、公司与 Capture 选择仍可恢复。
- 覆盖 Capture 多选回调在下游控件 rerun 前写入 selected IDs。
- 合表筛选与附注号排序相关定向测试共 15 项通过。
