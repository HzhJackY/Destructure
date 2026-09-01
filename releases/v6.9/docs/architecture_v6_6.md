# v6.6 架构说明：权威锚点驱动抓取

## 权威链路

`Selected Statement Anchor → Statement Child → Note Reference → Certified Note Target → Capture Plan → Job`

`DISCOVERED_NOT_SELECTED` 仅保留机器证据、审核历史和训练候选；它不是抓取输入。

## 附注解析

候选生成按 Section、Ordinal、标题语义和后续表格特征排序。候选与认证结果分离：候选宽召回，只有人工确认的 `CERTIFIED_NOTE_TARGET` 可进入执行。

## 发布与数据

本 release 位于 `releases/v6.6`，不改写 `releases/v6.5.1`。DATA_HOME 继续共享；SQLite 创建表均为 `IF NOT EXISTS` 的前向追加迁移，原始 PDF、机器证据、人工审核和既有 captures 不被重写。
