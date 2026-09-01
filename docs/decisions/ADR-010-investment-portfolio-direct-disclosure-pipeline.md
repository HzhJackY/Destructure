# ADR-010 — 投资组合直接披露表的 Family 专属认证与正式管线复用

状态：ACCEPTED

## 背景

`investment_portfolio` 与 `financial_investment` 是不同经济口径。上市母公司年报中的
投资组合可按投资对象、按会计计量或两者披露；直接套用金融投资的固定成员集合与附注
Stage B 会产生确定的错误阻断。

## 决策

- `INVESTMENT_PORTFOLIO_V2` 使用 `DIRECT_PORTFOLIO_TABLES`，但仍由既有
  `GenericDiscoveryService` 调度。
- Stage A 认证物理页、披露拓扑、适用分类轴、物理资产数量和来源披露总额；不调用
  金融投资成员门禁。
- Stage B 为每个物理表认证 `DIRECT_PORTFOLIO_WHOLE_TABLE`。硬门禁为物理 ROI、页码、
  标题、物理资产 ID 和行均位于 ROI；附注 inventory 与附注列签名不适用。
- 认证后继续走唯一正式链：Whole-table Capture → CaptureDecisionReducer → Canonical
  Long → Merge → User Research XLSX。
- Direct 列上下文使用 N-lane V2 物理签名，不假定固定四列；跨期变动列保留
  `period_kind=PERIOD_CHANGE` 与可空 `year`。认证 leaf 几何、期间和量度映射不一致
  时 fail-closed。
- 新生成的 Direct 列上下文在 N-lane V2 leaf 证据上增加 V3 父期间列组：保存日期 anchor、
  连续列组 bbox、父/子表头行带、已消费 span 和 lane group。同行结构按左侧父期间优先、
  右侧惩罚回退；多行结构先建立列组范围再映射叶子列，左右距离只作无法建立范围时的回退。
  父期间消费后的日期 span 不得重新进入 measure；残片以
  `PERIOD_FRAGMENT_IN_MEASURE_LABEL` fail-closed。
- Direct 复合表按认证 `classification_axis` 识别逻辑块，展示标题只是文案，不是
  物理轴身份。一个物理 ROI 可物化为多个 bundle 子 Capture，Merge 从根 Capture
  按 bundle graph 展开。
- `DIRECT_PORTFOLIO_PHYSICAL_ROI` 与普通附注 manifest 是两种明确的边界验证模式。
  Direct 模式仅在认证/Runtime segment、selected/physical manifest、行归属全部一致且
  无 drift 时产生硬边界，不依赖“下一附注标题”。
- Golden 只做读后比较，不得写回或填补机器证据。
- Direct 复合表可条件物化 `portfolio_summary / PORTFOLIO_SUMMARY`：仅消费首个认证轴
  标题之前的有效数值源行，不新增 ROI、认证目标或 required member。总览、投资对象和
  会计计量保持同一 CaptureBundle 内的独立语义身份；category 继续作为兼容根。
- Discovery、逻辑分块与标题归一共用投资组合轴语义识别器；未知 `按…` 边界进入
  `UNRESOLVED` 审核。数值源行归一必须满足 page/bbox/source-value 守恒，不能因清理标题
  而删除或复制。
- Direct 项目名称使用共享的证据化正规化合同：`raw_item` 保留 PDF 原文；
  `normalized_item` 作为 Canonical/Merge 名称身份。尾随数字括号只有原生上标几何或同页
  编号注释证据成立时剥离，证据单独持久化；无证据候选保留并进入行级审核。
- Direct 物理 Capture 在单元格构造前消费 Stage A 认证金额单位。单位按 observation/measure
  归属：金额为认证金额单位并可计算 `value_yuan`，占比和增减率为 `%` 且不计算人民币值。
  表级 `result.unit` 只保留兼容默认值。
- Merge 以 `normalized_item` 生成 source key，并只在同一 measure 内检查单位冲突。研究宽表
  不再输出固定“单位”列；每个数值列通过 `currency_unit + measure` 表头表达单位。
- Direct 新认证写入 V4 期间签名：在 V3 父期间列组几何上保存完整点期间结构和稳定
  `period_identity`。Canonical/Merge 以 `period_identity + scope + restated + measure` 识别列，
  `data_year` 降级为兼容字段。完整日期、月和年精度不得互相降维；历史 V3 Capture 只读派生，
  同年不同日期保持独立 observation。研究宽表显示 `period_label`，精度差异单独输出非阻断
  `PERIOD_PRECISION_MISMATCH` 审计。
- `machine_discoveries` 的 Direct 候选 ID 先标识稳定 PDF/成员/主表页身份；重放时若仅置信度、
  候选页、bbox、状态或 evidence JSON 变化，追加确定性的 `__R<sha256>` 机器证据版本，
  不覆盖旧快照，并将返回的新版本 ID 传给 Guided occurrence。稳定身份变化仍以
  `MACHINE_DISCOVERY_IDENTITY_CONFLICT` fail-closed。
- 附注组件和混合拓扑保留在合同中，但没有正向上市母公司样本前不得声称已完成。

## 后果

金融投资原有 Stage A/B 不放宽；投资组合不再受其固定成员或附注审核逻辑污染。直接
披露中的单表、复合表和同页双表保留独立且可审计的物理/逻辑身份。
跨年度脚注号变化不再制造重复项目身份，金额和比例也不再被压缩为行级混合单位；原始标签、
脚注证据和逐 observation 单位仍完整保留在 Canonical Long provenance 中。历史 Capture
不迁移，必须通过重新 Capture 才能取得新合同数据。
