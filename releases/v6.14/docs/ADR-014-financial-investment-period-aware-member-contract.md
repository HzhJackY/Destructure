# ADR-014：金融投资成员与期间联合身份合同

## 状态

已采纳（v6.14）；v6.13 保持冻结。

## 背景

金融投资主表在新旧准则过渡年度可能在同一物理表中同时披露两套成员：当前期使用新准则成员，比较期和期初列保留旧准则成员。成员名称是否“出现”不足以判断当前期覆盖；`不适用` 也不是抽取缺失。

原有 Registry 与 Statement Family Resolution 已能给出 `NEW_IFRS9`、`LEGACY` 和 `MIXED_TRANSITION`，但 Evidence V2 和排名曾重新硬编码新准则四成员，形成第二套冲突语义。

## 决策

1. 金融投资成员的正式证据身份为 `(member_table, period_identity, period_role)`，不得只按标签或页面出现性认证。
2. Registry 与 Statement Family Resolution 是 presentation regime、必需当前期成员、可选当前期成员和比较期成员的唯一合同来源。Evidence V2、排名、OCR 恢复、Stage B 和 UI 只消费同一快照。
3. 当前期单元格明确区分 `VALUE_PRESENT`、`LEGAL_DASH`、`NOT_APPLICABLE` 和 `UNRESOLVED`。比较期的有效值不能补足当前期门禁；当前期 `不适用` 不能被当成抽取漏值。
4. Stage A 只以动态 `required_current_members` 检查主表可认证性。历史或比较期成员保留为审计证据，但不制造当前期主表硬阻断。
5. Stage B 只为当前期、可进入附注抓取的成员生成 `CertifiedChildTableLink` 候选；比较期、非激活成员以非阻断状态展示，不伪造子表任务。
6. OCR 恢复顺序保持：原生证据 → 已定位候选页 OCR → 仍无唯一合格候选时才全文 OCR。OCR 不得覆盖明确 scope 冲突或错误期间。
7. 旧字段继续作为只读兼容投影；不得建立平行 Capture、Canonical 或 Merge 语义。

## 影响

- 纯新准则、纯旧准则和同表混合披露共用一条动态成员管线。
- 中国人保 2023 的新准则当前期成员可通过门禁；旧准则比较成员仍被保留，不再被误判为当前期缺失。
- 过渡表中未被 OCR 稳定识别的可选历史成员形成 coverage gap，不会包装成当前期绿色覆盖。
- Whole-table Capture、Reducer、Canonical、Merge 和 Golden 均未改变。

## 回退

仅撤销 v6.14 的 period-aware contract 模块及其消费者，恢复旧 V2 兼容行为；不触及 v6.13、Golden、PDF、认证资产或 DATA_HOME。
