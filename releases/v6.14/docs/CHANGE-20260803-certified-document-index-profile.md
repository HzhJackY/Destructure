# Change Report — 认证 OCR Profile 收敛

## 修改范围

新增 `document_index_profile.py`，并让 Fast Index 默认配置、GUI 的 Generic Discovery、`build_text_index()` 语义适配器、条件 OCR 与 `run_12_filing_matrix.py` 从该模块读取同一 profile。

## 不变事项

- 未修改研究定义、阶段 B、Capture、合表、SQLite schema 或 DATA_HOME。
- OCR 数值仍不会进入认证金额通道。
- `auto` 与 `selected` 仍仅代表页面选择策略。

## 验证

- 编译通过。
- 16 项定向单元/兼容测试通过。
- 中国太保 2023 年报通过 GUI 后端同一 `GenericDiscoveryService`，在统一 400 DPI 之下定位 PDF 第 74 页与附注七-10、11、12、13。

## 风险

首次访问旧 300 DPI 缓存的文档会新建 400 DPI 索引，耗时增加；缓存文件仍由 DPI 隔离，不会混用。
