# Streamlit Golden Corpus 验收

阶段 A 的主报表 Anchor 在认证前，会读取项目根目录的 `golden_corpus/v1.1.0`。该语料库是只读的独立基准，不从当前 Discovery、Capture 或 Merge 写回。

对已覆盖公司/年份，界面逐项比较金融投资成员、附注序号和当期金额：

- `MATCH`：允许继续正常认证；
- `MISMATCH`：展示 Golden 与实际发现值，阻止自动认证，需先人工核查 PDF；
- `NO_GOLDEN`：保留通用人工审核路径；
- `GOLDEN_UNAVAILABLE`：不得视作验收通过。

Golden 比对不修改任何机器证据、人工裁决或财务金额。

## 子表 UI E2E 参考

对已覆盖的中国平安 2023 与新华保险 2023，阶段 B 还会读取
`page_anchors.yaml`，在认证子表关系前比较成员、附注序号、候选 PDF 页和标题。
不匹配时不允许认证该链接。此处验证的是主表到附注明细表的真实导航链路；
当前 Golden 未提供附注表的单元格级明细值，因此不会将它错误表述为最终 XLSX
数值全链路验收。

## 子表细项数值对照

Golden 的 `child_table.items` 已提供时，研究任务审核中心会对实际 Capture 的
`table_raw_long.csv` 逐行、逐期比较。当前期与已重述比较期分别按 `data_year` 和
`restated_flag` 对照，括号负数保留负号语义。

复合附注可以拆成多个 Capture Block；对照前会聚合同一 `capture_bundle_id` 的全部
Block，避免把后续“上市/非上市”等分类行误报为缺失。只有所有 Golden 观察值均吻合，
才显示细项数值通过；该检查仍不改写原始 Capture 或自动替代人工认证。
