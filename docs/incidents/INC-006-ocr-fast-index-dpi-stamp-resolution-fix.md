# Incident Report INC-006: OCR 识别退化、表名印章遮挡与 FastIndex 渲染修复

## 1. 事发现象 (Symptom)
在太保 2023 年报与 2025 年报的扫描图片页（如 PDF p74）提取过程中出现：
1. 太保 2023 `持有至到期投资` 金额留空（显示为 `NaN`）。
2. 太保 2025 页面顶部的 `合并资产负债表` 表名无法识别，显示为杂质字符 `<区光:`，导致作用域判定位 `UNKNOWN`。

---

## 2. 根本原因分析 (Root Causes)

经过底层比对与全量日志核查，定位到了 4 个叠加的技术根源：

### ① 局部 XObject 子图抽取 Bug (Sub-image Extraction Bug)
旧版 `fast_index.py` 优先尝试提取 PDF 内部的原始嵌入图片对象（`page.get_images()`）。当 PDF 页面包含局部水印/裁切子图时，提取出的不是整页报表，导致送入 Tesseract 的图片被严重失真。

### ② `words_to_rows` 错误的单字框宽高比旋转判定 (Rotation Misclassification)
`words_to_rows` 行聚合逻辑中使用了 `(x1 - x0) < (y1 - y0)` 判定词框是否为纵向。由于中文字符 bbox 天然为方块或纵长矩形，导致正常的直立中文页面被 **100% 误判为 90 度旋转**，并被强制施加了 `(-y1, x0, -y0, x1)` 坐标转置，导致行聚合严重破坏。

### ③ 红色审计印章遮挡表名 (Red Auditor Stamp Obscuration)
太保 2025 年报 PDF p74/p75 顶部表名 `合并资产负债表` 上盖有红色的会计师事务所审计印章。在普通二值化下，红墨迹与黑字重叠粘连，导致 Tesseract 识别为杂质 `<区光:`。

### ④ PIL 重存丢弃 DPI 元数据 (PIL Image Metadata Loss)
在使用 PIL `Image.open` 重新保存 PNG 时未显式携带 `dpi=(400,400)` 标头，导致图片 DPI 降级为 72 DPI，破坏了 Tesseract 内部的字号/排版分割算法。

---

## 3. 正式修复路线与规范 (Certified Architecture & Fix)

为了避免未来误用任何旧路线设置，现明确以下 **OCR 解析标准规范**：

1. **统一全页高 DPI 渲染与标头保留**：
   - 必须使用 PyMuPDF `page.get_pixmap(dpi=effective_dpi)`（默认 >= 400 DPI）对整个 PDF 页面进行完整渲染。
   - 必须保存图像 DPI 元数据（`pix.save(tmp_path)` 或 PIL `dpi=(400,400)`），严格禁止转存为 72 DPI 默认图片。

2. **强制开启 Scheme A 红色印章过滤 (Red Stamp Removal Filter)**：
   - 在进入 Tesseract OCR 之前，必须进行 RGB 红色通道过滤：
     `RedInkMask = (R > 120) and (R > G + 30) and (R > B + 30) -> white`
   - 将红色印章墨迹置白消隐，确保表名 `合并资产负债表` 及科目文字清晰可见。

3. **废除单字 Aspect-Ratio 旋转 Heuristic**：
   - 严禁根据 CJK 中文字符框的宽高比进行页面旋转推断。页面旋转仅依赖 PDF 元数据 `page.rotation`。

4. **主表行解析器模糊正则别名 (Fuzzy OCR Regex)**：
   - 在 `CpicRowParser` 等解析器中保留容错模糊正则匹配（如 `持.*至.*到` / `持至到投资`），保障 TSV 词组切分下的稳健绑定。

---

## 4. 验证结论 (Verification Results)
- **太保 2023**：`持有至到期投资` 金额 `487,672,416` 及附注 `8` 100% 成功提取。
- **太保 2025**：`合并资产负债表` 表名 100% 成功识别，作用域准确判定为 **`CONSOLIDATED`**。
- **太保 2023-2025 全量**：主表金融投资科目全部 4/4 完整抽取。
