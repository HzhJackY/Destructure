# INC-044 — 无桥接成员生成无 schema 空文件

状态：`RESOLVED_FORMAL_MERGE_REACCEPTED`

## 现象

金融投资 V6 增强验收首次运行得到 11/12 PASS。中国人寿 2023 的 `time_deposits` 按设计
不参与跨准则桥接，bridge long 为 0 行；旧投影器却将空列表直接构造成无列 DataFrame，
使两个正式 Merge 的桥接 CSV 存在但没有 V1 列头。

## 根因

旧验收只检查文件存在和 manifest 计数，未核验零行产物的 schema。投影器仅在存在 bridge
row 时从数据推导列，混淆了“业务上无桥接 observation”和“交付合同不存在”。

## 修复

- `financial_investment_standards_bridge.py` 为 bridge long、bridge wide 和 audit 定义固定列集；
  无 bridge membership 时仍写稳定空 schema。
- 原始口径 observation 完整保留；audit 写 `NO_STANDARDS_BRIDGE`，不制造桥接值。
- `RegistryAcceptanceHarness` 校验四产物、schema/manifest 版本、行数、阻断值为空、审计覆盖
  和同期间多来源禁止求和。

## 验证

- 新增无桥接成员零行 schema 回归。
- 重新生成隔离正式 Merge 30/30，V6 四产物合同 30/30 PASS。
- 金融投资 V6 Stage A、Capture/Golden、UI/Offline 和最终七阶段均为 12/12 PASS。
- 生产 DATA_HOME、Golden、PDF 和 v6.13 未修改；浏览器 E2E 为 `SKIPPED_BY_USER`。
