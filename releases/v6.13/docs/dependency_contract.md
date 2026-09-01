# v6.12 公开候选依赖合同

状态：`DEPENDENCY_CONTRACT_READY_FOR_PUBLIC_PRERELEASE`

## Python 版本

- 合同范围：CPython `>=3.11,<3.15`。
- 当前只读盘点环境：CPython `3.14.5`、Windows amd64。
- `3.11–3.13` 以及 Linux/macOS 的干净环境安装仍为 `NOT_RUN`，不能从当前快照推断已验证。

## 依赖分组

| 分组 | 直接依赖 | 用途 |
|---|---|---|
| core | Streamlit、Pandas、OpenPyXL、tabulate、PyMuPDF、pdfplumber、PyYAML | UI、表格处理、PDF 原生文本/几何、Excel 输出、配置读取 |
| ocr | NumPy、Pillow | 仅用于条件 OCR 图像预处理；复用 core 的 PyMuPDF |
| llm | OpenAI、Google GenAI、Pydantic | DeepSeek/OpenAI-compatible 与 Gemini 的显式可选客户端 |
| dev | pytest | 合成与单元回归；不包含真实 PDF、Golden 或浏览器 E2E 工具 |

`openai`、`google-genai` 和 `pydantic` 在提供者实例化时才导入，因此离线确定性路径不要求安装 LLM 分组。NumPy/Pillow 只在 OCR 函数调用时导入。

`pyproject.toml` 的默认 pytest 配置显式忽略 `tests/user_journeys`。该目录声明了外部 `pytest-playwright` 与已运行 Streamlit 服务，但公开 dev 分组不安装这条 E2E 工具链；这与本轮“跳过全部 E2E”的验收边界一致。

## 系统依赖

OCR 分组不能通过 pip 独立闭合。扫描页兜底还要求：

- Tesseract OCR 5.x 可执行文件；
- `chi_sim` 语言数据；
- 可执行文件可从 `PATH` 找到，或使用代码当前支持的 Windows 标准安装位置。

本轮未调用 Tesseract、未运行 OCR，也未处理真实 PDF。

## 安装入口

本仓库是从检出目录运行的扁平源码应用，不作为 wheel 打包。`pyproject.toml` 通过 `tool.uv.package=false` 明确这一点。

在隔离虚拟环境中可选择：

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-ocr.txt
python -m pip install -r requirements-llm.txt
python -m pip install -r requirements-dev.txt
```

每个可选 requirements 文件都包含 core，适合单独执行。本轮已在全新 Windows /
CPython 3.14.5 环境使用规范 `uv.lock` 完成 core + dev 安装；该证据只证明依赖可安装，
不替代测试、真实 PDF 或发行认证。

## 锁定证据边界

规范锁文件为 `uv.lock`，由隔离工具环境中的 uv 0.12.3 从
`pyproject.toml` 解析生成：

- 覆盖 Python `>=3.11,<3.15` 的统一解析；
- 记录 75 个直接/传递包、来源及发行文件哈希；
- `uv lock --check` 已通过；
- 安装必须使用 `uv sync --frozen`，禁止在发布验证时重新解析版本。

`requirements.environment-snapshot.txt` 只保留最初 CPython 3.14.5 /
Windows 环境的 74-pin 审计快照，不参与安装约束。首次干净安装暴露
PyYAML 6.0.2 在 Python 3.14 缺少 wheel、回退源码构建需要 MSVC；直接
依赖已更新为 PyYAML 6.0.3 并重新生成锁。随后
`uv sync --frozen --extra dev --no-install-project` 成功，空 DATA_HOME 合成 Smoke
与固定预期完全一致。公开安全 pytest 集合在修复后为 346 passed。浏览器 E2E、
真实 PDF、Golden、Discovery/OCR 与生产 DATA_HOME 仍按用户范围未运行，所以只能
升级为公开预发行，不能升级为生产发行认证。

`sbom.cdx.json` 是由 uv 0.12.3 从冻结锁导出的 CycloneDX 1.5 依赖清单，覆盖 core、
OCR 和 LLM 运行时 extras；它不包含项目许可证决定，也不等同于第三方许可审核。

## 许可选择与 Windows 二进制合同

当前直接依赖 PyMuPDF 1.27.2.3 的包元数据显示其采用 AGPL-3.0 / Artifex
Commercial 双重许可。维护者已选择项目 `AGPL-3.0-only` 与 PyMuPDF 的 AGPL 路径。
Windows companion 资产提供固定 PyMuPDF sdist、Python wheel 哈希锁、OCR conda
包、许可证、recipe、上游源码 URL 与哈希。

不得将当前依赖快照或 SBOM 单独视为 NOTICE、许可证正文或 corresponding source
的替代品。完整记录见 `docs/windows_runtime_provenance.md`。

## 排除边界

开发依赖只来自保留的合成/单元测试 import 面。已删除或不分发的真实 PDF、Golden、用户 DATA_HOME、缓存、浏览器 E2E 以及内部 OCR 基准环境均未用于扩张公开依赖集合。
