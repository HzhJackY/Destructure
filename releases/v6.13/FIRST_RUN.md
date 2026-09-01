# 首次运行说明

## 先确认边界

GitHub 预发行提供两种使用方式：

- Windows x64 用户优先下载完整便携包：无需另装 Python 或 Tesseract，先双击
  `Portable_Self_Check.cmd`，通过后双击 `Launch_AXA_Research.cmd`。
- 源码 ZIP 面向开发、审阅和其他平台，需要按下文安装 Python 依赖。
- 两者都是公开预发行，不是生产认证版。
- 它不附带真实年报 PDF、Golden、用户 DATA_HOME、缓存、数据库、密钥或个人配置。
- 公开证据只覆盖空 DATA_HOME 合成 smoke 与公开安全测试；浏览器 E2E、真实 PDF、Golden、Discovery/OCR 和生产 DATA_HOME 未运行。
- 请只用自己拥有、获得授权或明确可再分发的文档进行后续实验。

正式发行状态和已知门禁见 [README.md](README.md) 与 [docs/release_policy.md](docs/release_policy.md)。

## 1. 前置条件

推荐 Windows 10/11、64 位 Python `>=3.11,<3.15`。本候选的已记录干净环境证据为
Windows / CPython 3.14.5。

推荐安装 [uv](https://docs.astral.sh/uv/)；也可以使用 `pip`，但 `uv.lock` 是本候选的
锁定依赖入口。先在解压后的 ZIP 根目录打开 PowerShell：

```powershell
py --version
uv --version
```

如果没有 `uv`，先按其官方安装说明安装；不要把 `.venv`、下载的依赖或工具缓存提交回源码目录。

## 2. 创建隔离环境并安装

在 ZIP 根目录执行：

```powershell
uv sync --frozen --extra dev --no-install-project
```

这会使用锁文件创建本地虚拟环境并安装核心与开发测试依赖。OCR 与 LLM 不是首次验证的前置条件；
它们需要各自的系统依赖、配置和授权，见 `requirements-ocr.txt`、`requirements-llm.txt`。

若不使用 `uv`，可创建虚拟环境并按 `requirements-core.txt` 与 `requirements-dev.txt` 安装，
但这不等同于本候选已记录的锁定安装证据。

## 3. 配置一个全新的空 DATA_HOME

不要指向现有项目、生产或个人 DATA_HOME。示例：

```powershell
$env:FIN_METRIC_DATA_HOME = "$env:TEMP\axa-research-v6121-evaluation"
New-Item -ItemType Directory -Force -Path $env:FIN_METRIC_DATA_HOME | Out-Null
```

目录布局与兼容性规则见 [docs/public_data_home_contract.md](docs/public_data_home_contract.md)。

## 4. 首次验证（不使用真实数据）

先运行确定性的合成 smoke：

```powershell
uv run python examples/synthetic/run_smoke.py
```

预期：退出码为 `0`，输出 JSON 的 `status` 为 `PASS`，且
`business_records_created` 为 `0`。随后可运行公开安全测试：

```powershell
uv run pytest -q
```

v6.12.1 的公开安全测试记录为 `346 passed`。你本地的结果可能因 Python、操作系统或依赖解析环境而不同；
若不同，请保留完整输出，不要修改 expected 或跳过测试来制造通过结果。

## 5. 可选：启动本地界面

只有在完成上述合成验证后，才可在你的空 DATA_HOME 中启动：

```powershell
uv run streamlit run app.py
```

这只启动本地界面，不会提供真实报告、Golden 或预置研究结果。不要把 API key 写入源码、
命令历史或提交的文件；本地 LLM/OCR 配置应放在 `.gitignore` 覆盖的配置位置。

## 6. OCR、LLM 与真实 PDF

- Windows 完整包已带 Tesseract 5.5.3、Leptonica 1.87.0 和 `chi_sim/eng/osd`；
  源码 ZIP 用户仍需自行安装或配置 OCR 运行时。
- LLM 为可选能力；自行提供密钥并遵守服务商条款，不要随 ZIP 分发密钥。
- 将真实 PDF 放到源码目录外，并确认处理、存储和再分发权限。
- 不要把 OCR 输出、Golden、缓存或捕获结果重新打入此 ZIP。

## 7. 常见问题

| 现象 | 处理 |
| --- | --- |
| `uv sync --frozen` 失败 | 核对 Python 版本、网络/镜像与 `uv.lock`；不要删除或改写锁文件。 |
| smoke 无法创建 DATA_HOME | 确认 `FIN_METRIC_DATA_HOME` 指向可写的新空目录。 |
| 想处理真实年报 | 先确认数据权利与 OCR/LLM 环境；这超出源码审阅 ZIP 的已验证范围。 |
| 想公开发布二次修改版 | 遵守 [LICENSE](LICENSE)、NOTICE 和第三方组件义务，并重新完成发布门禁。 |

## 8. 从伴随包离线重建 Windows 便携包

```powershell
pwsh -File .\tools\rebuild_windows_portable_from_companion.ps1 `
  -SourceRoot . `
  -CompanionRoot C:\path\to\corresponding-source `
  -WorkDirectory C:\temp\axa-v6121-work `
  -OutputDirectory C:\temp\axa-v6121-portable
```

四个目录必须相互隔离；work/output 必须不存在。脚本不会联网，并逐项验证固定输入哈希。

## 9. 下载自检

随 ZIP 提供的 `.sha256` 与 manifest 可验证下载是否完整。Windows 完整包还应与
corresponding-source/provenance companion 一起下载；它包含运行时来源、许可证、recipe、
wheel 和对应源码。哈希一致只证明文件一致性，不等同于生产功能认证。
