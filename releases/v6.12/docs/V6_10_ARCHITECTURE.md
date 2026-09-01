# v6.10 架构说明

## 口径与身份

`StatementScopeSelection` 在 Anchor 前建立研究口径。`BOTH` 被拆为
`CONSOLIDATED` 与 `PARENT_COMPANY` 两条独立 lane；scope 继续进入
Anchor Child、Certified Link、CaptureRequest 及下游逻辑身份。

## 分级发现

每份 PDF 只建立一次正式财务报表附注标题索引。发现按 Tier 1 显式引用、
Tier 2 研究定义标题、Tier 3 主表原始标签依次执行。上一级唯一且无冲突时
立即早停。候选保持轻量，表结构和金额只在 Top-K 页局部验证。

## 认证边界

`ThinChildTableCandidate` 与 `ChildTableLinkCandidate` 都不是执行凭证。
人工确认产生不可变的 `CertifiedChildTableLink` 后，系统才能构造
`CaptureRequest` 并交给统一 Orchestrator。

## 审核与学习

歧义关系进入 `child_mapping_review_queue`，统一审核收件箱可路由至
“子表映射”。人工接受、覆盖、拒绝、无对应表、补充表与 abstain 均保留
为版本化审核记录；本版本未声称训练了正式机器学习模型。

## 兼容性

v6.10 是独立代码 release，v6.9 不修改。生产 DATA_HOME 连续共享，
schema 12 仅增加表，不重写历史 evidence、capture 或 certified knowledge。
