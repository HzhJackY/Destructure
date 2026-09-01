# INC-022 — 新华其他权益工具投资短表语义轴未解析

## 现象

新华保险 2023/2024 年“其他权益工具投资”的“股票 / 未上市股权 / 合计”在机器宽表
按年度拆成两组行。2023 合计 5,370 百万元同时出现在 2023 Capture 与 2024 年报比较列，
但没有跨 Capture 对齐。

## 根因

Research Definition 的 `other_equity_investment` 成员没有声明权威
`classification_axis`，且该字段没有从 Discovery 候选传入 CaptureRequest。
新华 2023/2024 短表只有“股票 / 未上市股权 / 合计”，没有独立 SECTION_HEADER，
因此 Capture 只能按行内证据回退为 `UNRESOLVED`。

ADR-009 要求 unresolved Block 按物理 `table_block_id` 隔离。两个年度 Block ID 不同，
Merge 正确执行保护策略，但由上游错误轴状态造成假拆行。

## 修复

- 在 Research Definition 成员合同中声明 `classification_axis=ASSET_TYPE`。
- 将该字段沿 Discovery → certified target/plan → CaptureRequest → CaptureService
  透传；compound 引擎只消费这个权威 hint，不再按成员名或行标签硬编码推断。
- 无权威 hint 且无显式行内轴信号时继续 `UNRESOLVED`，由 ADR-009 的 fail-closed
  规则保护错误合并。
- 不修改 Merge 的 Block 隔离合同，不按同名或同值强制合并。

## 验证

- 多 Block Capture 与跨年度对齐测试：19 passed。
- 静态编译检查通过。
- 未重新运行 PDF/OCR，也未改写现有 Capture 或 Merge Project；旧 Capture 仍需正式
  重新 Capture 后才会获得新的轴元数据。
