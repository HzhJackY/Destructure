# INC-017 — 中国人寿 Stage B 只显示/抓取 2023（重复认证附注容器冲突）

## 现象

- 用户对中国人寿 2023/2024/2025 三年年报执行 ① 发现 + ② 认证所选 Anchor 后，
  Stage B“抓取逻辑表”只显示 2023 年的附注表；点击“确认逻辑表并抓取”后实际
  只生成中国人寿 2023 的抓取作业（5 个，SUCCESS）。
- 数据库证据：10:53:29 创建了研究批次 RB_d396...，执行会话
  `STAGEB_2816be6e...__V7e3b...` 包含今晨历史计划（太保 ×9 + 国寿2023 ×1），
  仅国寿2023 计划产生新作业。

## 根因

1. **重复认证产生全新候选树**：10:52 的新 discovery 为同一 PDF/附注容器创建了
   新 occurrence / candidate / inventory-candidate / logical-candidate（新 ID），
   与 09:10–10:06 已认证的 inventory/links（旧 ID）冲突。
2. **自动认证死路**：`_auto_certify_inventory_links` 先 `certify_note_table_inventory`
   创建新 CINV，随后 `certify()` 的“同附注容器只能有一个 inventory”一致性检查
   发现旧链接引用旧 CINV，抛 `NOTE_TABLE_INVENTORY_ID_MISMATCH`；由于
   `unresolved_inventory_cases` 为空，`assign_global` 对所有子表返回
   `AUTOMATION_REPAIR_REQUIRED`，`automatic_certification_count=0`。
3. **UI 静默回退**：0 条 certified links + 0 未决映射时，`render_guided_capture`
   落入 restore-only 分支展示历史会话；旧格式计划（无 certified_note_target/
   segment manifest）被“抓取逻辑表”过滤，仅新格式的国寿2023 计划可见；确认后
   执行了历史会话而非本次认证结果。

## 修复

- `hierarchical_child_discovery.py` 新增 `_adopt_existing_container_links`：
  当同一附注容器（source PDF + leaf note ordinal）已有 CERTIFIED inventory 且
  内容等价（成员+分类集合一致、PDF digest 未漂移、容器内 inventory ID 唯一）时，
  直接采用既有 certified links，不再创建平行 inventory，避免
  `NOTE_TABLE_INVENTORY_ID_MISMATCH` 死路。
- `guided_workflow_ui.py`：认证零产出时 fail-closed——显示明确错误并返回，
  不再用历史会话计划代替本次认证结果。

## 回归

- `tests/test_v611_certified_child_segments.py::test_recertification_of_certified_note_container_adopts_existing_links`
- UI 源码不变式（零产出错误文案）加入 `test_v611_stage_b_persistence_integration.py`。
- 定向 49 passed；邻接回归 78 passed；合计 127 passed。

## 边界

- 仅自动认证路径采用内容等价复用；手工 `certify()` 的跨 inventory 冲突仍抛
  `NOTE_TABLE_INVENTORY_ID_MISMATCH`（`test_same_note_requires_one_inventory_id`）。
- 未删除历史会话；浏览器 E2E 仍按用户约定暂停。
