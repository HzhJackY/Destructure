# CHANGE — v6.13 精简身份架构

日期：2026-08-17

状态：`IMPLEMENTED_TARGETED_VALIDATION`

## 变更

- `TableRow` 增加稳定源行身份、父项身份、行来源和父子证据字段。
- Spatial 数值父项推断写入 `parent_row_id`，保留金额闭合证据。
- Direct 原生恢复不再执行会清空父子关系的二次扫描，冲突只写审计证据。
- Long 序列化使用稳定源行身份，并保留已认证行角色。
- 结构解析器优先消费已认证父项，不覆盖正式关系。
- Merge 单位冲突键统一处理 nullable 期间维度。

## 验证边界

- 定向 Capture/身份/单位测试通过。
- 未运行浏览器 E2E。
- 真实 PDF Canary、DATA_HOME 破坏性迁移和全量 Merge 仍需执行。
