# INC-029：数据资产管理中心缺少单个 PDF 生命周期

## 现象

数据资产管理中心的 PDF 页签只能查看上传文件和 Capture 引用数，不能删除或回收单个 PDF。

## 根因

`PdfRepository` 与 `PdfService` 只有 `list()`；现有“旧数据完全清除”只能备份后整体移走全部
uploads，不是单资产生命周期。PDF 作为源证据的保护原则被实现成了完全无操作入口。

## 修复

- 增加 ACTIVE/TRASHED 状态、原路径、回收路径和回收时间。
- 增加逐 PDF 依赖扫描：动态检查所有 `pdf_id`、`source_pdf_id`、`source_pdf_path` 及同类标量
  身份列。任何引用均 fail-closed。
- 零引用 PDF 可移动到 `uploads/_trash`，支持原位恢复；目标冲突和路径越界均拒绝操作。
- 永久删除只允许 TRASHED PDF，要求精确确认 token，并清除对应 SHA cache/text index。
- 所有生命周期事件进入 `registry_events`；不级联删除其他资产。
- 全量 Registry sync 只清理失踪的 ACTIVE 索引，保留 TRASHED 记录。

## 验收与边界

隔离 DATA_HOME 覆盖回收、恢复、永久删除、三类引用门禁、错误 token、同步保留、陈旧 upsert
与路径越界。未运行浏览器 E2E；未删除用户真实 PDF。
