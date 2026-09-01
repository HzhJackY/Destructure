# v6.0 Data Asset Management Guide

## A whole extraction batch is wrong

Go to:

```text
数据资产管理 → Captures
```

Filter the affected records, then:

```text
选择全部筛选结果
→ choose invalidation reason
→ 批量废除 INVALIDATED
```

Recommended reason for parser duplication:

```text
HEADER_TOPOLOGY_ERROR
```

The Capture evidence remains stored.

Dependent Merge projects are marked stale automatically.

---

## Re-run the rejected data with the newest parser

Select the invalidated Captures:

```text
批量重新抓取
```

A new batch is created.

Old and new Captures are linked by supersession metadata.

---

## Delete obvious test/debug runs

Use:

```text
批量移入回收站
```

Permanent deletion should be performed only from:

```text
数据资产管理 → 回收站
```

---

## Manage a whole batch

Go to:

```text
数据资产管理 → Batches
```

Select one or more batch IDs.

Available actions:

```text
废除所选批次
重新运行所选批次
所选批次移入回收站
```

---

## Check whether a Merge is stale

Go to:

```text
数据资产管理 → Merges
```

Run:

```text
重新检查全部 Merge 依赖状态
```

Possible result:

```text
CURRENT
STALE_SOURCE_INVALIDATED
STALE_SOURCE_MISSING
```

---

## Correct structural data rather than deleting it

For a single Capture:

```text
数据资产管理 → Captures → 单条 Capture 预览 / 结构审核
```

Use, in order:

```text
表头算法裁决
列拓扑复核
表头维度复核
边界复核
```

Do not invalidate data merely because a correct human structural adjudication can repair it.
