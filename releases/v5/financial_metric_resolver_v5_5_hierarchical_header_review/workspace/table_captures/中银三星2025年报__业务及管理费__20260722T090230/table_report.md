# 整表抓取报告

- PDF: `e115146901c4_中银三星2025年报.pdf`
- 查询表: `业务及管理费`
- 定位标题: `六、 财务报表附注（续）34. 业务及管理费和其他业务成本`
- 页码: `133–134`
- 实际表格页: `133, 134`
- 列数: `4`
- 行数: `49`

## 列结构

- col0: year=2025 | scope=本集团 | restated=False | raw=本集团 | 2025
- col1: year=2025 | scope=本公司 | restated=False | raw=本公司 | 2025
- col2: year=2024 | scope=本集团 | restated=True | raw=本集团 | 2024 | （已重述）
- col3: year=2024 | scope=本公司 | restated=True | raw=本公司 | 2024 | （已重述）

## 警告

- 未发现下一附注编号作为硬结束边界，当前使用max_pages边界，请人工核对末尾。

## 说明

- `raw_item` 永久保留PDF原始行名。
- `normalized_item` 只做确定性文本清洗，不改变经济含义。
- `canonical_item` 整表抓取层默认不强制映射；跨公司细项统一由“合表 / Taxonomy”工作区完成。