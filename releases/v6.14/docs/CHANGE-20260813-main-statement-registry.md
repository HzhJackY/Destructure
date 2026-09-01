# Change Report：v6.13 主表 Registry 与用户 Registry

## 范围

- 基线为 v6.12.1 公开源码 ZIP 的 237 项清单；建立隔离目录 `releases/v6.13`。
- 没有回写 `releases/v6.11` 或 `releases/v6.12`，也未触碰用户 DATA_HOME、既有 Capture、
  Canonical、Merge、Golden 或真实 PDF。

## 变更

- 增加两个内置 Whole-table Registry：合并资产负债表、合并现金流量表。
- 增加 `DIRECT_MAIN_STATEMENT_TABLE`，在同一 Generic Discovery 和
  CertifiedChildTableLink owner 内认证主表整表及连续页 segment。
- 增加用户 Registry 草稿、结构校验、单事务启用、审计与内置项服务层只读保护。
- Generic Discovery 拒绝 DRAFT/ARCHIVED Definition，避免 API 或旧会话绕过 UI 下拉。

## 验证边界

- 定向 pytest：27 passed。
- 中国人寿 2025、中国平安 2025 各运行资产负债表和现金流量表 Definition 的最小原生文本
  Discovery Canary；均未触发 OCR。
- 未运行浏览器 E2E（用户要求跳过）、既有整批抓取、真实 PDF Capture/Canonical/Merge、
  Fresh Golden 或公开发行验证。因此本目录状态为 `DEVELOPMENT_CANDIDATE`，不可作为
  GitHub Release 资产上传。
