# 抓取入口审计

v6.7 存在三条生产路径：Streamlit 直接调用 `capture_named_table`、Guided Service
直接向旧 Runner 入队、`CaptureService.create` 直达底层执行。v6.8 已统一为：

`UI/Guided/Batch/Retry → CaptureRequest → CaptureOrchestrator → certified target gate
→ CaptureService._execute_resolved_target → registration confirmation → logical version`。

`generic_discovery.PRESETS` 的运行时变异桥已移除；历史 preset 仅保留为导入数据源。
底层 `capture_named_table` 只在唯一执行器内部调用。

