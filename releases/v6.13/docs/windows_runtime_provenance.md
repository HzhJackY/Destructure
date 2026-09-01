# Windows 完整包运行时来源与重建合同

状态：`PUBLIC_PRERELEASE_RUNTIME_PROVENANCE_COMPLETE`

本合同只适用于 v6.12.1 Windows x64 便携预发行包。它不改变冻结的
`releases/v6.11`，也不把浏览器 E2E、真实 PDF、Golden、Discovery/OCR 或生产
DATA_HOME 验收标记为已运行。

## 固定输入

| 输入 | 固定版本/来源 | 校验方式 |
|---|---|---|
| CPython | 官方 Windows embeddable x64 `3.14.5` | 发行伴随包记录下载 URL、字节数与 SHA-256 |
| Python 运行依赖 | Windows / CPython 3.14 的 55 个 wheel | `python_windows_cp314_requirements.lock` 的逐包 SHA-256；构建使用 `--no-index --require-hashes` |
| Tesseract | conda-forge `tesseract 5.5.3 he87eeb8_0` | conda 包 URL、SHA-256、recipe 和许可证文件 |
| Leptonica | conda-forge `leptonica 1.87.0 hb83fb89_1` | 同上 |
| OCR DLL | 从 Tesseract 可执行文件解析出的 42 文件闭包 | 每个文件 SHA-256 和所属 conda 包记录 |
| 中文/英文/方向语言数据 | `tessdata_fast` 提交 `87416418657359cb625c412a48b6e1d6d41c29bd` | `chi_sim`、`eng`、`osd` 分别固定 SHA-256 |

完整包不会复制构建机上“所有 DLL”，不会从互联网重新解析 Python 版本，也不会包含
训练工具或未使用语言包。构建脚本对 42 个 OCR 文件与 3 个语言文件逐个校验哈希，任何
缺失或变化都会失败。

## 发行资产

GitHub 预发行至少同时提供以下三项：

1. 公开源码标签/源码 ZIP；
2. `AXA_Research_v6.12.1_windows_x64_full_public_prerelease_20260812.zip`；
3. `AXA_Research_v6.12.1_corresponding_source_provenance_20260812.zip`。

从源码根目录执行 `tools/rebuild_windows_portable_from_companion.ps1`，只需指定解压后的
source、companion、全新的 work 与 output 目录；脚本离线验证并组装 CPython、pip
bootstrap、55 个运行 wheel、42 个 OCR 文件与 3 个语言模型，然后调用正式 builder。
两个不同绝对工作路径的实测输出清单为 7,539/7,539，非 manifest 文件 SHA-256 差异 0。

第 3 项包含实际 conda 二进制包、包级许可证、构建 recipe、上游源码 URL/哈希、
CPython 输入、55 个 wheel、wheel 哈希锁、三个固定 `tessdata_fast` 文件与语言锁、
PyMuPDF 1.27.2.3 sdist，以及含完整
`thirdparty/` 树的 MuPDF 1.27.2 官方源码。它用于离线重打包和履行
许可证所要求的源码可得性；不能把单独一个 SBOM 当作其替代品。

## 许可证边界

- 项目源码采用 `AGPL-3.0-only`，完整正文在顶层 `LICENSE`。
- PyMuPDF 选择其 AGPL 路径；伴随包同时提供绑定层 sdist 和 wheel 内嵌 MuPDF 1.27.2
  （包括静态 OCR 等 `thirdparty/` 源码）的官方 source tar。
- Tesseract 和 tessdata_fast 为 Apache-2.0；Leptonica 为 BSD-2-Clause。
- OCR 运行闭包还包含 LGPL、BSD、MIT、Zlib、curl、Microsoft 运行库等组件；逐项文本、
  来源和哈希随伴随包提供。
- conda-forge `libarchive 3.8.9 gpl_he24518a_100` 静态包含 LZO 2.10；LZO 为
  GPL-2.0-or-later，本 AGPL-3.0-only 聚合选择其 GPLv3 兼容路径。伴随包提供 LZO
  完整源码、许可证、recipe 与源文件 SHA-256。
- `libiconv 1.18` 为 LGPL-2.1-only，以 `iconv.dll/charset.dll` 动态保留可替换性；
  相同伴随包提供其精确二进制、许可证、recipe 和上游源码哈希。
- `NOTICE` 和组件矩阵是信息性记录，不替代各组件许可证正文。

## 可复现声明

这里的 `repackaging_reproducible=true` 表示使用已固定并随发行提供的二进制输入可重建
相同运行时内容。它不表示所有第三方二进制都能从源码得到逐字节相同结果；因此
`source_rebuild_bit_reproducible=false`。

## 已验证与未验证

- 已验证：固定输入哈希、Python 核心导入、Tesseract 版本和语言枚举、空 DATA_HOME
  合成 Smoke、公开安全测试 346 项。
- 未运行（用户明确跳过）：浏览器 E2E、真实 PDF、Golden、Discovery/OCR、生产
  DATA_HOME。

所以可以公开上传为 `PUBLIC_PRERELEASE_UPLOAD_READY`，但不得标为
`PRODUCTION_RELEASE_CERTIFIED` 或声称真实年报 OCR 准确率已经验收。
