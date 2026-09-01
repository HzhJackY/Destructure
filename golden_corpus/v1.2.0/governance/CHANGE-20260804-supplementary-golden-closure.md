# Change Report - Supplementary Golden 缺口补齐

Date: 2026-08-04
Change Log ID: `ACL-1.1.4-SUPPLEMENTARY-GOLDEN-CLOSURE`

## Changed

- 新增新华保险 2023 两张 ECL supplementary，共 44 个金额槽位。
- 新增中国人寿 2024 债权投资公允价值层级 supplementary，共 16 个金额槽位。
- 新增中国人寿 2025 债权投资双期间 stacked 公允价值层级 supplementary，共 32 个金额槽位。
- 四张表均登记为独立 `SUPPLEMENTARY_TABLE`，没有伪造 `CONTINUATION_SEGMENT`。
- 修正中国人寿 2024 segment registry 的附注章节“十、”为 PDF 原文“十一、”。
- 单期间 schedule 显式记录 `period`；治理校验不再要求原始标题必须带“年度”才能识别当前期。

## Evidence

- 三份 canonical PDF 的 SHA256 与 filing identity 完全一致。
- PDF reader p188/p189、p186、p168 的 2x 原图逐页视觉核验。
- 同页文本层逐行核对期间、分类轴、行序、金额及 `－/–` 占位槽。
- 表尾后的下一附注标题用于确认 peer boundary；未从 Capture/parser 输出反推金额。

## Release State

- 新增表与金额完成 Golden 认证。
- 在其余 bounded note/continuation 审计完成前，相关 filing 的 `ALL_NOTE_TABLES` 仍保持阻断；本变更不以已认证计数替代“无续段”证据。

## Rollback

删除三个 supplementary YAML 和四条 segment registry 记录，恢复三条 coverage 行及国寿 2024 原 registry 身份字段；保留本报告和页面证据供审计。
