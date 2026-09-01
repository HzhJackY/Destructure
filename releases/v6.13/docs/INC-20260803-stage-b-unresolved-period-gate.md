# INC-20260803 — Stage B 将未解析期间状态错误过滤

## 现象

四公司 Child 缓存清理后的真实 PDF 冷启动中，新华保险、中国太保与中国人寿的主表子项带有 `member_period_status=UNRESOLVED`。旧逻辑把任何非 `ACTIVE_CURRENT_PERIOD` 状态都排除，导致阶段 B 生成零个 Child 概念。

## 根因

`UNRESOLVED` 被误当成“明确不是当前期”。它只表示期间解析未完全认证；并不否定主表当前期金额和显式附注编号。

## 修复

仅明确的 `COMPARATIVE_ONLY_LEGACY_MEMBER`、`OUTSIDE_FAMILY`、`NOT_A_FAMILY_MEMBER` 被排除。`UNRESOLVED` 子项进入阶段 B，但保留 reviewable period-policy 审计标记，不能自动冒充人工认证。
