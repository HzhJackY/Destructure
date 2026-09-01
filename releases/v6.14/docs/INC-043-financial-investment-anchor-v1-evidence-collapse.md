# INC-043：金融投资主表 V1 证据折叠

## 症状

中国人保 2023/2025 等报告中，正确合并资产负债表可能因旧固定 2023/2022 列和横坐标二次解析失败；另一些报告会因“首张=合并、第二张=母公司”后备规则而把母公司页带入合并 lane。

## 根因

主表发现、排名和 UI 不是同一证据对象：发现层可得来源页，排名层却另调 `capture_statement_anchor()`，后者采用固定年份和坐标。scope 与请求 lane 混写，附注缺失又会删除成员行。

## 修复与回归

v6.14 引入 ADR-012 的 V2 合同，移除排序中的旧二次 capture、保留真实 source scope、以动态期间/BBox 绑定列，并将 Child Link readiness 与 Anchor 身份分离。扫描页没有 BBox 的情况必须保留 fail-closed，而非补写 Green。

## 后续根因补充：OCR 触发断点

中国人保 2023 的原生文本足以命中标题、scope、父项和成员，所以旧 Discovery 认为“已找到目标页”而跳过 OCR；V2 随后才发现期间与金额 BBox 缺失，却没有回传给 OCR 层。该断点会把正确页错误地留在 `period_recognized/value_geometry` 门禁外。

ADR-012 的三级恢复将发现、候选证据补全和全文兜底收敛到同一 Fast Index 页缓存。2026-08-24 的隔离产品级验证中，中国人保 2023 第 142 物理页以 `CANDIDATE_EVIDENCE_RECOVERY` 恢复 278 个 OCR 词级 BBox、当前/比较/期初三列、4/4 成员和附注 3/4/5/6；范围不包含 Capture 或 Golden 写入。

## 后续验收根因补充：恢复候选与 Golden 页身份

全文恢复以唯一、全硬门禁通过的物理页组作为服务发现结果；验收比较器不得只按冻结 Golden 页号重新筛掉该候选。若服务唯一候选与 Golden 物理页不同，必须报告 `BLOCKED_GOLDEN_IDENTITY_MISMATCH`，保留服务证据并阻断转正；不得把它误报为 Discovery/Capture 失败，也不得由机器回写 Golden。新华保险 2025 的第 120/121 页差异是该规则的首个回归样本。

## 后续根因补充：过渡年度成员合同被 V2 再次硬编码

中国人保 2023 的同一张合并资产负债表同时包含新准则当前期成员与旧准则比较期成员。旧 Registry 和 Statement Family Resolution 已能输出 `MIXED_TRANSITION` 及动态成员集合，但 Evidence V2、排名分母和 Stage B 补行曾重新硬编码新准则四成员，丢失“成员 × 期间”关系。这会把合法的比较期 `不适用` 误报为成员缺失，并可能不必要地升级至全文 OCR。

v6.14 按 ADR-014 改为消费 Registry 驱动的合同快照：当前期门禁仅检查动态必需成员，比较期和历史成员保留审计身份但不制造当前期阻断；`不适用`、合法破折号、有效值与抽取缺失使用不同状态。Stage A、Stage B、OCR 恢复和 UI 由同一快照投影，未修改 Whole-table Capture、Reducer、Canonical 或 Merge。

## 后续根因补充：OCR 标签替换 Native 身份

中国人保 2023 的 Native 标签行可确认新旧准则成员，但 Tesseract 的“贷款”等个别字形可能误识别。旧 V2 在 OCR 几何可用时整体采用 OCR 成员集合，造成错误标签有机会改写 `member_table`；同时 Native 与 OCR 使用 points/pixels 两套坐标，无法严格验证同一行。

修复后，Fast Index 为 OCR BBox 持久化坐标元数据，V2 将 OCR 统一换算为 PDF points。候选页恢复以 Native `source_row_id/member_table` 为身份锚点，OCR 匿名数值行仅在纵向 BBox、附注审计和数值 lane 一对一通过时补充期间、金额与 BBox。OCR 标签降级为审计字段；冲突和歧义保持 fail-closed。

## 后续根因补充：Evidence V2 只存在于内存

排名入口曾能在内存中构建完整 Native V2 或 OCR recovery evidence，但 Guided UI 随后的认证入口按原始 occurrence ID 重新读取 Registry，得到的仍是缺少 V2 的首次机器发现。因此界面看似已经恢复，正式候选却再次退回 `period/value geometry` 缺失。

v6.14 将成功的 Native V2 与 OCR recovery 都物化为 append-only evidence revision；修订 ID 由 filing、原 occurrence、完整 evidence 和 child rows 的内容哈希确定。排名、UI 和后续认证读取同一 revision，原始机器发现不被覆盖。中国人保 2023/2025 产生 `OCC_REC_*`，2024 产生 `OCC_EVD_*`，三份均保持唯一合并 scope 候选。
