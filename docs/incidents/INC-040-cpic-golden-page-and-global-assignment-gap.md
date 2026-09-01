# INC-040：太保 Golden 旧物理页与全局分配缺口

## 现象

太保 2023–2025 已切换为当前上市母公司 PDF，`filing.yaml`、`page_anchors.yaml` 和
`golden_values.yaml` 已更新，但金融投资 v1.2 identity sidecar 的物理页仍保留旧 PDF 页码。
同时，认证任务生成了 Stage B 候选并保存局部链接/repair 统计，却未调用正式
`assign_global()`，因此生产库没有太保的 `global_child_assignments`。

## 根因

1. `validate_identity_sidecar()` 仅验证单文件内部身份、行 ID、父子图和期间字段，没有把
   sidecar 与同目录 source Golden/filing 交叉核对。
2. 一次性认证脚本复制了部分 Stage B 逻辑，并在脚本内自行分流 auto/repair，绕过正式
   全局分配 owner service。

## 修复

- 修正太保三年 sidecar 的 12 个 current primary 页码及 2023 年 3 个历史物理表页码。
- 新增 `validate_identity_source_consistency()` 并接入 `RegistryAcceptanceHarness` 的
  Corpus Preflight；来源页码或 filing 身份矛盾时 fail-closed。
- 生产 metadata 完整备份后，通过正式 Discovery/Enrichment/Link/`assign_global()` 处理
  3 个已认证 Anchor，持久化 3 个 assignment 与 13 个 AnchorChild decision。

## 验收边界

- Golden/Corpus 定向测试与全量 pytest 必须通过。
- 生产库写前/写后 `PRAGMA integrity_check` 必须为 `ok`。
- 双 Registry acceptance 继续如实报告缺少 Capture、历史成员认证和既有 Capture/Golden
  差异；本事故关闭不等于 24 个 filing-profile 全链 `COMPLETE`。
- 不运行浏览器 E2E。
