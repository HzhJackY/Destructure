# INC-026 — 中国太保本地语料法律实体身份错配

状态：RESOLVED_FOR_INVESTMENT_PORTFOLIO_GROUP_CORPUS / LEGACY_FILENAME_LOCK_REMAINS

## 事实

复核后，2024、2025 已更新为上市母公司年报；原 `docu/中国太保2023年报.pdf` 仍因外部
进程锁定而保持太保寿险文件，另以 `docu/中国太保集团2023年年度报告.pdf` 保存并锁定
上市母公司 2023 年报。

## 影响

- 不能用这三份子公司披露报告代表上市公司投资组合披露拓扑。
- 不能把其四个金融投资附注组件自动相加为投资组合总额。
- 在法律实体映射修复前，这三份报告只可作为 `MULTI_NOTE_COMPONENT_SET_NO_REPORTED_TOTAL` 的负向设计证据，不得晋升为投资组合 Golden。

## 本轮处理

- 从中国太保官网取得并哈希锁定 2023–2025 上市母公司年报，仅放在当前任务证据目录。
- 新增投资组合 Golden 时使用 `CPIC_GROUP` 独立身份，未覆盖既有 `cpic` 金融投资 Golden。
- 未修改生产 DATA_HOME、既有 Capture、Canonical 或作业。

## 后续门禁

投资组合 Golden 已统一使用 `CPIC_GROUP` 身份与三份上市母公司 PDF：2023 物理页 48、
2024 物理页 50、2025 物理页 48，均为 `DIRECT_COMPOUND_TABLE`，3/3 Stage A Golden
匹配且未使用 OCR。原 2023 寿险文件未被破坏性覆盖；它不再参与投资组合上市母公司矩阵。
