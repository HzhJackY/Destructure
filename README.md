# AXA Research v6.12.1

> 状态：`PUBLIC_PRERELEASE_UPLOAD_READY` · `NOT_PRODUCTION_RELEASE_CERTIFIED`

AXA Research 是面向保险公司年报的 PDF 表格发现、认证抓取、规范化与研究合表工作台。v6.12.1 是公开候选的合同修复版，延续原生文本优先定位、候选页条件 OCR 与可复用页级 OCR 缓存。

本目录可作为 GitHub 公开源码预发行候选。Windows 完整包使用固定的 CPython、
wheel、Tesseract、Leptonica、DLL 与中文语言数据输入，可由随发行的 companion 资产
离线重打包。它仍不是生产认证版；真实数据链路与用户要求跳过的 E2E 没有被补跑。

首次在新电脑使用此源码候选，请先阅读 [FIRST_RUN.md](FIRST_RUN.md)。它说明依赖安装、
空 DATA_HOME、合成验证和真实数据/OCR 的明确边界。

Windows 用户还可使用内置 Tesseract 中文 OCR 的便携预发行包；其范围与限制见
[docs/windows_portable_prerelease.md](docs/windows_portable_prerelease.md)。它可作为公开
GitHub **pre-release** 资产，但不是生产认证正式版。

## 当前边界

- 应用版本：`v6.12.1`
- 元数据注册表 schema：`15`
- DATA_HOME 布局 schema：`6.10`；它是持久化数据布局版本，不等于应用版本
- 发行状态：`PUBLIC_PRERELEASE_UPLOAD_READY / NOT_PRODUCTION_RELEASE_CERTIFIED`
- v6.11 保留为内部冻结回退基线，不默认纳入此公开候选
- 本候选不得包含真实年报、用户 DATA_HOME、Golden、缓存、SQLite 数据库、运行日志或密钥
- 项目采用 `AGPL-3.0-only`；使用、修改或分发前须遵守 [LICENSE](LICENSE) 及所有第三方组件的许可证义务

许可证决定见 [LICENSE_SELECTION_REQUIRED.md](LICENSE_SELECTION_REQUIRED.md)，公开分发边界见 [docs/public_distribution_boundary.md](docs/public_distribution_boundary.md)。

## 正式处理链路

```text
Canonical PDF
→ Main Statement Resolution
→ CertifiedChildTableLink
→ Whole-table Capture
→ CaptureDecisionReducer
→ Canonical Long
→ Merge
→ User Research XLSX
```

不得用独立脚本绕过这条主链路，另建平行 OCR、Capture、Review、Canonical、Merge 或导出流程。OCR/LLM 只提供受控候选或证据，不能生成或修改财务金额。

## v6.12 系列重点

- 先使用 PDF 原生文本定位主表，不为整本 PDF 预建高 DPI OCR 索引。
- 原生证据不足时，仅对受界定的候选页执行条件 OCR。
- 页级 OCR 结果由 Fast Index 缓存统一复用，避免平行 OCR 管线和重复计算。
- 保留扫描件与扫描目录页的受控兜底，并记录失败与缓存来源。
- 保持 Certified Anchor、CertifiedChildTableLink、完整 Capture 和合表治理链路不变。
- 对不同经济分类轴保留独立资产身份，例如资产类型、计量构成和上市状态不会因同处一个物理段而混合。

## 本地评估

完整步骤和故障排查见 [FIRST_RUN.md](FIRST_RUN.md)。以下仅保留最短命令索引：

公开评估应使用全新的空 DATA_HOME，禁止指向生产或个人历史目录：

```powershell
$env:FIN_METRIC_DATA_HOME = "C:\path\to\empty-evaluation-data-home"
uv sync --frozen --extra dev
python -m streamlit run app.py
```

以上命令只用于源码候选的本地评估。Windows 完整包另有固定输入重打包合同。本轮已在全新
Windows / CPython 3.14.5 环境用 `uv sync --frozen --extra dev --no-install-project`
完成安装，并使空 DATA_HOME 合成 Smoke 与预期输出完全一致；测试门与许可门仍须
分别判断。

DATA_HOME 的目录与版本合同见 [docs/public_data_home_contract.md](docs/public_data_home_contract.md)。首次评估只能放入自有、获授权或明确可再分发的文档；项目不附带真实保险公司年报。

公开测试的包含/排除边界和当前失败节点见
[docs/public_test_contract.md](docs/public_test_contract.md)。

## 数据与证据治理

- SQLite `metadata.db` 是控制面索引，不是财务数据主存储。
- PDF、JSON、CSV、Parquet 等证据保留在 DATA_HOME 中，默认不进入源码仓库。
- Capture 机器证据不可由预览或人工修订静默覆盖；人工决策另行审计。
- 父子表算术不一致是可审计警告，除非另有明确阻断合同，不应自动篡改金额。
- `report_year` 表示年报来源年份，`data_year` 表示数字对应的会计年度，两者不可互换。

## 安全、贡献与许可证

- 安全问题请遵循 [SECURITY.md](SECURITY.md)，不要在公开 issue 中披露密钥或真实业务数据。
- 贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，测试夹具只能使用合成或明确获准再分发的材料。
- 本项目许可证为 `AGPL-3.0-only`；`NOTICE` 记录项目与第三方许可注意事项，不替代许可证正文。
- PyMuPDF 的当前依赖元数据为 AGPL-3.0 或 Artifex Commercial 双重许可。本候选选择
  AGPL 路径，并在 Windows companion 资产提供固定版本对应源码。

## 预发行限制

- 公开安全测试 v6.12.1：`346 passed`；浏览器 E2E、真实 PDF、Golden、Discovery/OCR 和生产 DATA_HOME 链路按本次范围未运行
- GitHub 上传必须同时提供源码、Windows 完整包、corresponding-source/provenance companion 和各自 SHA-256
- GitHub Release 必须勾选 **Set as a pre-release**；不得声称真实年报 OCR 准确率或生产验收已通过

完整包来源与重建合同见
[docs/windows_runtime_provenance.md](docs/windows_runtime_provenance.md)。
