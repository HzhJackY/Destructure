# ADR — 认证文档索引 Profile 唯一来源

## 决策

生产 Fast Index、GUI 主表发现、语义索引兼容层、条件 OCR 与四公司离线认证矩阵统一使用 `document_index_profile.py` 的 `FINANCIAL_TABLE_400DPI_V1`。

## 原因

原先离线认证显式使用 400 DPI，而 GUI Fast Index 默认使用 300 DPI。同一 PDF 可产生不同 OCR token、行重建和候选结果，不具备可复现性。

## 边界

`auto` / `selected` 是 OCR 页面选择策略，不是 OCR 质量 profile。OCR 数值仍不得直接进入认证金额通道。

## 缓存和回退

400 DPI 已包含在 Fast Index 缓存键中，与旧 300 DPI 缓存隔离。本变更不迁移 DATA_HOME、Capture 或人工认证。
