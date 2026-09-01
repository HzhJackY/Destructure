# INC-20260803 — 阶段 B 将 OCR 源行误作成员检索键

## 现象

阶段 B 曾显示类似“交易性金融资产 <附注号> <金额A> <金额B>”，主表金额为空，且严格分级召回返回零候选。公开 incident 不保留真实报告金额。

## 根因

主表 OCR 行同时包含项目、附注号和数值。旧链路把整行存入 `raw_label`，并把该字段同时用于 UI 显示、标准标题和 Tier 2 标题检索。标题索引中只有“交易性金融资产”，不可能精确匹配混入数字的字符串。另一个旧规则会正确隔离 OCR 数字，却把它显示成难以理解的空数组。

## 修复

- `source_line` 保留完整原始行；`raw_member_label` 保留已匹配的会计标签。
- 阶段 B 从 `canonical_concept_id` 查询 Research Definition，使用注册表标准标题、定义别名及会计标题变体检索。
- OCR 数值移动到 `ocr_amount_candidates`，只读显示为定位证据，绝不写入 `statement_amount_*` 或勾稽。
- Child Discovery 版本升级，旧检索缓存不再复用；Streamlit 会话中的旧映射必须回到阶段 A 重新认证。

## 不变约束

OCR 数字不能认证为主表金额，也不能解除 Capture / Merge 的金额审核。
