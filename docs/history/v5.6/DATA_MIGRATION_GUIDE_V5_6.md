# v5.6 Historical Data Migration Guide

## First upgrade to v5.6

Open:

```text
数据管理 → 历史版本迁移中心
```

Choose the old version root or its `workspace` folder.

Example:

```text
D:\FinancialResolver\v5.5
```

Click:

```text
扫描旧版本
```

Review detected assets, then:

```text
执行迁移
```

## What is promoted to the shared repository

```text
PDF                        YES
Machine Capture            YES
Boundary Review            YES
Header Review              YES
Capture metadata           YES
Batch / Run / Review       YES
Table Taxonomy             MERGE
L0 metric_aliases          MERGE
Cache                      NO
Old canonical Merge        ARCHIVE ONLY
```

## Why Merge is not automatically promoted

Merge is derived from:

```text
Capture + structural rules + taxonomy + current code version
```

Since newer versions may fix header dimensions, row order, or item identity, the safest workflow is:

```text
migrate Capture
→ review any new structural warnings
→ rebuild formal Merge
```

Old Merge Projects remain preserved under:

```text
DATA_HOME/archive/legacy_merges_<timestamp>/
```

## Future versions

After the first v5.6 migration:

```text
v5.7
v5.8
...
```

should read the same shared DATA_HOME through the stable user-level pointer.

Normally no workspace copy is needed again.
