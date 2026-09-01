# ADR-012：金融投资主表证据 V2

状态：已采纳（仅 v6.14；受 Shadow 转正门禁约束）  
日期：2026-08-24

## 决策

`StatementAnchorEvidenceV2` 是金融投资 Stage A 的唯一主表证据合同。它在受限的物理主表页上记录真实来源 scope、页组、标题与 BBox、期间列/角色/BBox、单位、附注列、成员行/单元格 BBox 和显式或隐式父项关系。

- Scope 按正式标题、续页继承、目录/章节证据、UNKNOWN 的顺序判定；不得按资产负债表页的出现次序推断。
- `source_statement_scope` 是不可改写的来源事实。合并 lane 中母公司页为 `SCOPE_CONFLICT` 硬门禁。
- 四个金融投资成员的主表身份由 Registry alias、成员行 BBox 和父项边界判定；无附注号仍保留成员，且只令相应 Child Link `NOTE_REFERENCE_UNRESOLVED`。
- 期间必须包含与 filing 年度相等的 CURRENT 列；金额仅绑定实际期间列，附注号只能来自显式附注列。
- `native_value_geometry_present` 只在标签、期间和当前金额均有实际 BBox 时为真。扫描/缺文字页必须走既有条件 OCR/cache 的恢复路径，不得由 V2 构造金额或新建 OCR 管线。
- 排名、兼容入口和 UI 都消费 V2；旧 `capture_statement_anchor()` 不再参与 Discovery 排名。Whole-table Capture、Reducer、Canonical、Merge 不改语义。

## 条件 OCR 与分级恢复（2026-08-24 补充）

V2 的硬门禁结果必须反馈给同一份 Fast Index OCR 服务；不能仅根据“Discovery 是否已找到标题页”决定是否 OCR。恢复状态机固定为：

1. `NATIVE_DISCOVERY`：原生发现；找不到目标页时保留既有最多 12 页的受控 OCR 搜索。
2. `CANDIDATE_EVIDENCE_RECOVERY`：候选物理页、scope、父项和报表类型已经正确，只缺期间、金额列/成员、单位或词级几何时，只 OCR 该页组。
3. `FULL_DOCUMENT_RECOVERY`：前两级没有任何全硬门禁通过的页组时，金融投资 Profile 才以 12 页一批扫描尚未 OCR 的页面。每批均重建 V2 并检查唯一性；唯一合格立即停止，两个及以上合格停止并返回 `ANCHOR_SELECTION_REQUIRED`，扫描至末页仍无合格候选返回 `OCR_FULL_SCAN_NO_QUALIFIED_CANDIDATE`。

每次候选页组或全文批次请求 Fast Index 时，索引构建必须限制于该请求页集；页集属于索引缓存身份。共享 OCR 页缓存仍按 PDF/引擎身份复用，因此不得为每个 12 页批次重遍历整份 PDF。

`SCOPE_CONFLICT`、错误报表类型、目标父项不存在和目录/摘要页均不得用 OCR 覆盖。OCR 只补充词级空间证据；原生与 OCR 的同字段冲突为 `NATIVE_OCR_CONFLICT`，fail-closed。

附注 lane 不得由页面中任意“附注/注释”文字扩展得出。V2 同时要求表头、至少两条目标成员行的同一纵向 lane、与期间列排他以及可规范化编号；金额、百分比、不适用或越过 `min(999,max(99,ceil(PDF页数/2)))` 的编号整体拒绝为附注列。连续、跳号、稳定重复和章节前缀子编号都是允许的强证据，非硬门禁。

期间规范化使用共享 `ReportPeriodContext`/`period_identity`，支持日期、年月、年份、季度、半年、重述期与期初列；同年不同季度以 `period_identity` 区分。`value_geometry_verified` 可由 Native 或经 V2 合同认证的 OCR BBox 满足，旧 `native_value_geometry_present` 仅保留兼容投影。

## 后果

无来源 scope、错当前期间、成员不足、无单位/几何或同一 filing/scope 有多份合格页组时不自动预选。UI 展示 V2 证据；人工 override 必须保存冲突证据与理由。

## Native 身份 / OCR 数值几何 Hybrid（2026-08-25 补充）

候选页原生文字已经足以确认标题、scope、父项和成员标签，但缺少可靠期间或数值几何时，V2 不得以 OCR 标签替换 Native 成员身份。恢复统一为：

- Native 保留 `member_table`、`raw_label`、`source_row_id`、父项关系、scope、标题和单位。
- Fast Index 的 Tesseract 词级像素 BBox 必须附带渲染尺寸与坐标元数据，并转换为 PDF points 后才允许与 Native 行 BBox 比较；旧缓存缺该元数据时只刷新请求页。
- OCR 先生成匿名数值行、期间 lane 和附注 lane；行对齐依赖纵向重叠、行序、附注一致性和期间数值 lane，OCR 标签只保存诊断。
- Hybrid 成功时 `geometry_evidence_mode=HYBRID_NATIVE_IDENTITY_OCR_VALUES`；`native_value_geometry_present` 保持 Native 事实，`value_geometry_verified` 和 `ocr_spatial_geometry_verified` 表示已验证的 OCR 几何。
- Native 缺附注时，OCR 附注号只能进入 alignment audit，不得形成正式 `CertifiedChildTableLink` 依据。
- OCR/Native 期间、金额、已存在附注或行映射冲突均 fail-closed；Hybrid 失败后保留 Native evidence，再由既有全文 OCR 扫描处理纯扫描件兜底。
- 兼容读取旧认证资产时，`financial_investment` 与 `FINANCIAL_INVESTMENT_V1` 均表示同一 Registry 路由；不得因历史 family key 跳过 V2 证据恢复或在 UI 中误排除“合并及公司”物理表。
- “合并及公司”是保留的真实来源 scope，但在用户明确选择合并或母公司 lane 时属于兼容物理来源；排序以兼容性计分，不能同时判定通过 scope 硬门禁又施加 scope 冲突扣分。
- 多 PDF 的候选页恢复按原 occurrence 逐项替换，完成某一 PDF 的 OCR 不得从同一轮 ranking 丢失其他 filing 的候选；恢复 revision 仅替代其自身原始候选。

## 行级新旧准则身份与 Golden 投影（2026-08-25 补充）

`FINANCIAL_INVESTMENT_MEMBER_CONTRACT_V6` 不再从年报级
`presentation_regime` 删除长 FVTPL 标签的另一准则身份。过渡年同一页可同时出现
“交易性金融资产”的当前期新准则行及“以公允价值计量且其变动计入当期损益的金融资产”的
比较期旧准则行；必须由该行的当前/比较期间单元格决定 `fvtpl_assets` 或
`legacy_fvtpl_assets`，不得由整份年报标签抢占行身份。

Golden Stage A comparator 同样必须保留同一稳定 member 的全部机器候选，并优先
`ACTIVE_CURRENT_PERIOD` 的来源行，再比较附注和金额。它不得因为一个合法的
比较期 legacy 行覆盖当前行而制造缺失，也不得用 Golden 反向改变机器身份。若当前
PDF 的附注与冻结 Golden 不一致，仍为真实 `MISMATCH` 并阻断自动认证。

V6 进一步要求同一页上的每个新旧准则 occurrence 都有独立 `source_row_id`；附注号、期间、
金额、BBox 先在该物理行内完成绑定，再投影 `presentation_member_id`。验收器不得从正式旧
Anchor 的 PASS 推断 V6 已通过，必须消费同一 PDF 的只读 Evidence V2 Shadow，并核对物理
行唯一性、必需当前期 occurrence 唯一性及跨行绑定冲突为零。
