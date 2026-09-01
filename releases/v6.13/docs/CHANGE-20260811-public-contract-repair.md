# Change Report：v6.12.1 公开候选契约修复

## 变更范围

仅外部公开 staging `v6.12.1-public-candidate`。冻结基线 `releases/v6.11` 与原始 `releases/v6.12` 未修改。

## 结果

- 项目声明 `AGPL-3.0-only`。这是 2026-08-11 的历史变更记录；其当时开放的第三方
  许可证/来源门禁已由 2026-08-12 的 Windows runtime provenance 与三资产联合发行闭包取代。
- 8 项失败契约均修复；公开安全测试由 `336 passed, 8 failed` 变为 `344 passed`。
- 多分块回归探针仅使用合成结构，不含真实 PDF、Golden、生产数据或浏览器。

## 未运行门禁

浏览器 E2E、真实 PDF、Golden、Discovery/OCR 与生产 DATA_HOME 按用户明确指令未运行。
当前状态已提升为 `PUBLIC_PRERELEASE_UPLOAD_READY / NOT_PRODUCTION_RELEASE_CERTIFIED`；
未运行项仍禁止将其称为生产认证版本。
