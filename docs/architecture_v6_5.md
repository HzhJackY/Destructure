# v6.5 架构说明：Statement-Anchored Table Family

## 核心对象

`display_name` 不等于一张可直接检索的表。v6.5 将其处理为研究目标：

`Statement Occurrence → Anchor Arbitration → Statement Anchor Table → Note Detail Tables → Certified Capture Plan`。

Statement Anchor 表保留父行（可为 `SECTION_PARENT`、值为空）及连续子项、金额、期间、口径和附注引用。每个子项同时是附注明细表的入口。金融投资的标准结果因此是 1 张主报表构成表和 N 张附注明细表，而不是 N 张彼此无关的表。

## 证据与审核

机器发现、人工裁决、认证知识三层独立保存。原始定位证据先按公司、年报、口径、成员和候选页聚类，审核对象不会因 TOC、标题、历史模板等多条路径而重复。审核分为：

1. Family Discovery Review：确认抓哪些成员；
2. Note Target Review：确认每个成员在哪里。

批量动作仍按每条机器发现写入独立审计记录和训练样本。

## 附注与页码

`note_reference` 是披露引用；`candidate_note_page` 是定位候选；`confirmed_note_page` 是认证结果。二者不等价。列头“附注八”和行号“9”会组合成 `附注八-9`。无显式附注引用时可进入标题、上下文、历史模板及全文回退，但低置信只能进入 `REVIEW_REQUIRED`。

PDF 页索引与印刷页码分别存储。bbox 若由上游解析器提供，审核预览必须高亮；没有 bbox 时页面仍可审核，但不能假装已高亮。

## ML / 模板

模型只排序候选、锚点、父子关系和附注定位，不产生数值。知识按 Global/Industry → Company → Filing Type → Statement Type → Scope → Family → Member → Historical Instance 回退。历史认证只复用结构与策略，必须重新验证新年度主表、引用、标题和对账。

## Release isolation

代码在 `releases/v6.4` 与 `releases/v6.5` 中隔离。DATA_HOME 由配置指针共享；迁移只新增 SQLite 表或列。代码回退不会删除 v6.5 数据，但旧代码不会理解 v6.5 专属认证计划/锚点元数据。
