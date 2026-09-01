# v6.13 Registry 用户合同

## 生命周期

```text
用户 JSON Bundle
→ DATA_HOME user_registry_drafts (DRAFT)
→ validate_user_draft
→ activate_user_draft（单事务）
→ table_families / family_members / research_definitions (ACTIVE)
→ Generic Discovery → Anchor 审核 → CertifiedChildTableLink → Capture
```

草稿不在 `families()` 或 `definitions()` 的 ACTIVE 查询中，因此不会被批次、知识包或
Discovery 静默消费。启用失败不会留下半个 Family 或半个 Definition。

## Bundle 最小结构

```json
{
  "family": {
    "family_id": "custom_direct_table",
    "display_name": "自定义披露表",
    "definition_version": "CUSTOM_DIRECT_TABLE_V1",
    "discovery_strategy": "DIRECT_NOTE_TABLE_FAMILY",
    "preferred_statement_types": ["NOTE_SECTION"],
    "preferred_scope": "CONSOLIDATED"
  },
  "members": [{
    "member_id": "custom_direct_table_member",
    "display_name": "自定义披露表",
    "member_role": "DIRECT_DISCLOSURE_TABLE",
    "required": true,
    "canonical_order": 1,
    "aliases": [],
    "row_signatures": [],
    "column_signatures": []
  }],
  "definition": {
    "definition_id": "CUSTOM_DIRECT_TABLE_V1",
    "display_name": "自定义披露表",
    "definition_version": "CUSTOM_DIRECT_TABLE_V1",
    "table_families": ["custom_direct_table"],
    "research_scope": {
      "core_members": ["custom_direct_table_member"],
      "optional_members": [],
      "excluded_members": []
    }
  }
}
```

首版只允许一个 Draft Bundle 对应一个新 Family。ID 必须以字母开头，只含字母、数字和
下划线；Definition 的成员引用必须属于本 bundle。用户不可覆盖或归档内置对象。

## 安全边界

- Registry 只保存结构、别名和治理元数据；不得把 PDF 原文、OCR 行、金额、真实页截图或
  未授权 Golden 写入 bundle。
- 启用不等于认证任何发现结果。每份 PDF 仍需在 UI 中审核 Anchor，并经过
  CertifiedChildTableLink 与 Whole-table Capture。
- OCR 仍仅是受控候选页定位证据，不能成为认证金额来源。
