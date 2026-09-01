# AXA_research Golden Lite — 四家保险公司 2023–2025 年报真实披露语料库 v1.1.0

存放路径：

`C:\dev\AXA_research\golden_corpus\v1.1.0\`

## 覆盖范围
本语料库覆盖四家主要保险公司 2023–2025 年共 12 份规范年报：
1. **中国平安** (2023, 2024, 2025) — `EXPLICIT_PARENT_STANDARD`
2. **新华保险** (2023, 2024, 2025) — `EXPLICIT_PARENT_MULTI_NOTE`
3. **中国太保** (2023, 2024, 2025) — `IMAGE_DOMINANT_EXPLICIT_PARENT` (页面锚点：2023: 74, 2024: 73, 2025: 74)
4. **中国人寿** (2023, 2024, 2025) — `IMAGE_BASED_IMPLICIT_MEMBER_SET_SCATTERED` (无金融投资母行)

## 核心设计与非循环验证
- 所有 PDF 均已绑定真实 SHA256 及绝对物理页码。
- 所有锚点均提供原图裁剪 (`evidence/page_crops/`) 与文本验证证据。
- **无自认证**：绝不将当前系统输出直接作为 Golden。
- **软件行为隔离**：Bug 和流程变迁归入 Defect Invariant Registry，不混入 Real Golden。

## 治理注册表（2026-08-04 迁移）

`filing_inventory.csv` 是仅含 12 份 canonical target filing 的不可变身份基线。迁移前
13 行版本保存在 `migration/filing_inventory.pre_governance_v1.1.0.csv`；不属于四公司
目标语料的候选保存在 `filing_exclusions.csv`，不得回流到 canonical inventory。

`golden_coverage_registry.csv` 每份 filing 一行，披露 Anchor、Pattern、主报表值、主逻辑
子表、补充逻辑子表和续段的覆盖、断言数量、当前/比较/重述期覆盖、审定信息和按 scope
划分的发布状态。

`golden_table_segment_registry.csv` 是事实明细：每一行是一个已审定的逻辑表根或物理段，
具有稳定 ID、页码、资产路径和 value assertion buckets。`CONTINUATION_SEGMENT` 必须带
已审定的 `continuation_of_physical_segment_id` 与关系证据；标题中的“续”不构成该关系。
当前 47 个明细包含 41 个 `PRIMARY_TABLE` 和 6 个 `SUPPLEMENTARY_TABLE`，没有已认证的
真实 `CONTINUATION_SEGMENT`。中国人寿 2023、新华保险 2025 的“续”标题资产均明确为独立
补充逻辑表。

运行 `python governance/validate_golden_corpus_registry.py` 可验证 CSV 回填是否仍与 YAML
Golden 和身份基线一致。验证器只读，不会写入或升级任何 Golden 事实。
