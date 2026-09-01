# v6.6 来源感知子表合并身份

## 观察身份

合表不能仅用项目名称、标准项目或行路径判断是否为同一观测值。v6.6 的逻辑观察身份为：

```text
table_family → member_table → member_table_role → row_path
  × company → report_year → data_year → scope → restated
  × period_type → currency → unit
```

只有上述来源语义与列维度都相同，才比较金额；相同金额可合并 provenance，不同金额为 `VALUE_CONFLICT`。缺失子表身份不进入金额比较，而产生 `REVIEW_REQUIRED_SOURCE_IDENTITY`。

## 数据流

```text
Certified Capture Plan
  → Capture metadata（表族/子表/角色/附注/顺序）
  → Job payload（旧 Capture 的恢复证据）
  → MergeService source-aware metadata
  → table_merge canonical key / structural order / materialization
  → Source Identity QA + Research Wide
```

`member_table_order` 先定义表族中子表顺序；每个子表仍使用自己的行层级和行顺序。宽表保留 `table_family`、`member_table`、`member_table_role` 和 `row_path`，内部 `canonical_key` 继续仅作审计字段。

## 中国平安 2023 验收

以金融投资四张附注明细表执行真实 PDF 抓取和合表。FVTPL、债权投资、其他债权投资中的“政府债”和“金融债”各保留三个 member rows；通用总额行保留四个 member rows；合表未出现真实 `VALUE_CONFLICT`。测试同时通过同一子表同维度异值的硬阻断回归。
