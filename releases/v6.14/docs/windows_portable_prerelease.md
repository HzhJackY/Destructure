# Windows x64 完整便携预发行包

该包将 CPython、核心 Python 依赖、Tesseract 5.x 与简体中文 `chi_sim` 一并放入发行目录。
用户无需预装 Python 或 Tesseract；双击自检后即可启动本地 Streamlit 界面。

## 公开状态

- 不包含任何真实 PDF、Golden、用户 DATA_HOME、缓存、数据库或密钥。
- 不捆绑 LLM 密钥；LLM 仍需用户自行配置。
- 浏览器 E2E、真实 PDF、Golden、Discovery/OCR 与生产 DATA_HOME 验收仍为 `NOT_RUN`。

Tesseract、Leptonica、实际 DLL 闭包、语言数据、Python wheel 与 PyMuPDF 的固定来源、
哈希、许可证和对应源码已随 companion ZIP 提供。因此本包可标记为
`PUBLIC_PRERELEASE_UPLOAD_READY / NOT_PRODUCTION_RELEASE_CERTIFIED`。

详细证据见 [windows_runtime_provenance.md](windows_runtime_provenance.md)。

## 运行时约定

- 启动器将内置 `runtime/tesseract` 放在 `PATH` 最前，并设置 `TESSDATA_PREFIX`。
- 默认 DATA_HOME 位于 `%LOCALAPPDATA%\AXAResearch\v6.12.1\data_home`；用户可先设置
  `FIN_METRIC_DATA_HOME` 覆盖它。
- 包内最小 OCR 语言数据为 `chi_sim`、`eng` 和 `osd`。未包含训练工具或其他语言包。
- 运行时为 conda-forge Tesseract `5.5.3`、Leptonica `1.87.0` 的 42 文件实际闭包；
  构建脚本会逐文件验证 SHA-256。
