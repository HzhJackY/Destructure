# 整表抓取报告

- PDF: `相对期间保险2025年度报告.pdf`
- 查询表: `业务及管理费`
- 定位标题: `34. 业务及管理费`
- 页码: `2–2`
- 实际表格页: `2`
- 列数: `4`
- 行数: `7`

## 列结构

- col0: year=本年累计数 | scope=本集团 | restated=False | raw=本集团 | 本年累计数
- col1: year=上年累计数 | scope=本集团 | restated=False | raw=本集团 | 上年累计数
- col2: year=本年累计数 | scope=本公司 | restated=False | raw=本公司 | 本年累计数
- col3: year=上年累计数 | scope=本公司 | restated=False | raw=本公司 | 上年累计数

## 警告

- HEADER_PARSER_AUTO_SELECTED：GENERALIZED_PERIOD_V57；numeric_clusters=4；leaf_columns=4。
- 未在目标附注首页识别到明确单位；原始单位保持UNKNOWN，不做金额单位推断。

## 说明

- `raw_item` 永久保留PDF原始行名。
- `normalized_item` 只做确定性文本清洗，不改变经济含义。
- `canonical_item` 整表抓取层默认不强制映射；跨公司细项统一由“合表 / Taxonomy”工作区完成。