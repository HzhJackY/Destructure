# 整表抓取报告

- PDF: `131df196d14b_交银人寿2024年报.pdf`
- 查询表: `业务及管理费`
- 定位标题: `32 业务及管理费`
- 页码: `121–122`
- 实际表格页: `121, 122`
- 列数: `4`
- 行数: `38`

## 列结构

- col0: year=2024 | scope=- | restated=False | raw=2024
- col1: year=2023 | scope=- | restated=True | raw=2023 | (已重述)
- col2: year=2024 | scope=- | restated=False | raw=2024
- col3: year=2023 | scope=- | restated=True | raw=2023 | (已重述)

## 警告

- 未在目标附注首页识别到明确单位；原始单位保持UNKNOWN，不做金额单位推断。
- 未发现下一附注编号作为硬结束边界，当前使用max_pages边界，请人工核对末尾。

## 说明

- `raw_item` 永久保留PDF原始行名。
- `normalized_item` 只做确定性文本清洗，不改变经济含义。
- `canonical_item` 整表抓取层默认不强制映射；跨公司细项统一由“合表 / Taxonomy”工作区完成。