# ADR-012：投资组合 Golden 父边与比较器差异语义

- 状态：ACCEPTED
- 日期：2026-08-23
- 范围：`INVESTMENT_PORTFOLIO_V2` Golden Identity v1.2 与验收比较器

## 背景

投资组合 source Golden 过去通过一个持续的 active GROUP 状态推导后续父项。物理表中
GROUP 结束后出现同级明细、合计或另一个分类段时，builder 会把这些行错误挂到旧 GROUP。
同时比较器把稳定身份连接失败扩散为多个字段差异，并把排版造成的原始标签差异作为阻断，
使一条父边问题被放大。

## 决策

1. source Golden 可用 `parent_row_order` 表达独立审阅父边；整数指向父 GROUP，显式
   `null` 表示 ROOT boundary。字段缺失时保留兼容构建规则。
2. 同级 GROUP、TOTAL 与显式 ROOT boundary 必须关闭 active GROUP。sidecar validator
   检查同 physical table/member/axis、父类型、父路径、悬空与环。
3. Runtime `parent_row_id` 仍由 Spatial Capture 单一写入。Golden builder 不读取机器
   Capture，也不写回 runtime 身份。
4. `raw_label` 降为 lineage audit；规范标签、row kind、稳定父路径/occurrence 与期间值才是
   阻断事实。
5. 稳定键失败但能够唯一配对时只输出一条 `semantic_identity` 差异；无法唯一配对时输出
   `identity_presence`，禁止把身份错误放大为多个数值字段错误。

## 验证边界

修复在隔离 DATA_HOME 对 11 份当前 canonical PDF 运行正式 Discovery → Capture →
Canonical → Merge，全部 Golden MATCH；逐行父子图审计全部匹配，且 v6.13 全量非 E2E
pytest 508/508 通过。太保 2024 不在本次 11 份范围内，因此本 ADR 不声明投资组合 12/12。
