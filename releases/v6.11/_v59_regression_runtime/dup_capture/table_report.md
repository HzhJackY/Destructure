# 整表抓取报告

- PDF: `dup.pdf`
- 查询表: `业务及管理费`
- 定位标题: `34业务及管理费`
- 页码: `1–1`
- 实际表格页: `1`
- 列数: `8`
- 行数: `1`

## 列结构

- col0: year=2024 | scope=本集团 | restated=False | raw=本集团|2024
- col1: year=2024 | scope=本集团 | restated=False | raw=本集团|2024
- col2: year=2023 | scope=本集团 | restated=True | raw=本集团|2023
- col3: year=2023 | scope=本集团 | restated=True | raw=本集团|2023
- col4: year=2024 | scope=本公司 | restated=False | raw=本公司|2024
- col5: year=2024 | scope=本公司 | restated=False | raw=本公司|2024
- col6: year=2023 | scope=本公司 | restated=True | raw=本公司|2023
- col7: year=2023 | scope=本公司 | restated=True | raw=本公司|2023

## 警告

- 表头维度存在碰撞/缺失：重复期间列无法由 year/scope/restated 唯一区分；请完成“表头维度复核”后再进入正式合表。

## 说明

- `raw_item` 永久保留PDF原始行名。
- `normalized_item` 只做确定性文本清洗，不改变经济含义。
- `canonical_item` 整表抓取层默认不强制映射；跨公司细项统一由“合表 / Taxonomy”工作区完成。