# v5.9 Parser Regression Corpus

This document defines parser behaviors that must remain stable across future versions.

## Case 1 — Standard absolute year, 4 columns

```text
                 本集团                    本公司
             2025  2024               2025  2024
```

Expected:

```text
4 logical columns
AUTO -> ABSOLUTE_YEAR_CLASSIC
```

Forbidden:

```text
8 duplicated columns
```

## Case 2 — Restated comparative

```text
本集团: 2024, 2023(已重述)
本公司: 2024, 2023(已重述)
```

Expected:

```text
2024 本集团 ORIGINAL
2023 本集团 RESTATED
2024 本公司 ORIGINAL
2023 本公司 RESTATED
```

## Case 3 — Split PDF tokens

```text
2024 + 年度
```

Expected:

```text
one leaf
```

## Case 4 — v5.7 relative period

```text
本年累计数 / 上年累计数
```

Expected:

```text
GENERALIZED_PERIOD_V57
4 logical columns under 本集团/本公司
```

## Case 5 — Wrapped accounting item

```text
当期发生的保费获取
    现金流
```

Expected:

```text
当期发生的保费获取现金流
```

## Case 6 — Formula reconciliation

```text
小计
减:
  A
  B
合计
```

Expected:

```text
BASE_MINUS_COMPONENTS
```

## Case 7 — Independent referee

```text
header leaves = 8
stable numeric clusters = 4
```

Expected:

```text
HEADER_OVERSEGMENTATION_VS_NUMERIC_CLUSTERS
REJECTED
```

## Case 8 — Safe topology fallback

Machine:

```text
8 duplicate logical columns
```

Human:

```text
KEEP 4
DROP_DUPLICATE 4
```

Expected:

```text
machine evidence = 8
official output = 4
```

## Case 9 — v5.8 actual-year resolution

2025 report:

```text
本年累计数 -> 2025
上年累计数 -> 2024
```

Original wording remains:

```text
source_period_label
```

## Command

```powershell
python tests\regression_v59.py
```

or:

```text
run_regression_v59.bat
```

All assertions must pass before a future parser release is considered regression-safe.
