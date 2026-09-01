# v6.8 架构说明

## 单一抓取链

所有 UI、Guided、批量与重跑入口先构造 `CaptureRequest`，再进入
`CaptureOrchestrator`。策略插件只负责发现和解析认证目标；唯一执行器为
`CaptureService._execute_resolved_target`。成功状态必须在物理 Capture 注册确认后产生。

## 逻辑资产与版本

逻辑身份由公司、报告类型、报告年度、口径、研究定义、表族、成员表和来源角色共同组成。
每次抓取产生不可变 `capture_versions`。只有新版本通过注册且质量认证后才成为 current；
失败或待审核重跑不会替换现有 current 版本。

## 生命周期

机器证据、人工审核和认证结果仍然分层。`review_queue` 只承载待处理版本；
归档通过状态和审计操作实现，不物理删除 Capture 证据。合表默认只接受
current + REGISTERED + CERTIFIED + CONFIRMED/AUTO_CONFIRMED + ACTIVE 的版本。

## 并发

`TableCaptureRunner` 使用非 daemon 线程，并提供 `join`、`shutdown` 和上下文管理。
批次摘要只在全部作业进入终态后写入。

