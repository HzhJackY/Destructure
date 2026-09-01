# Financial Metric Resolver v4.3 — Batch Fast Index + Optional OCR

v4.3 的目标是解决 v4.2 平均约 2 秒/页的全量深度扫描瓶颈，并支持多份年报批量提取同一组指标。

## 核心架构

```text
多份 PDF
   │
   ├─ Fast Index（PyMuPDF，只抽文本）
   │      └─ OCR: off / auto / force
   │
   ├─ L0 aliases / keywords 召回候选页
   │
   ├─ 仅候选页 ± 邻页执行 pdfplumber 深度解析
   │
   ├─ Fast Index 缓存 + 页级 Deep Parse 缓存
   │
   ├─ 多 PDF ProcessPool 并行
   │
   └─ 输出 long / wide / Excel / JSON
```

## OCR 三档

- `off`：默认、最快。文本型年报使用。
- `auto`：仅对原生文本少于阈值的页面 OCR。适合混合型 PDF。
- `force`：每页 OCR。适合纯扫描 PDF，速度会明显下降。

OCR 使用 PyMuPDF 集成 OCR / Tesseract。Tesseract 必须单独安装，并安装相应语言包，例如 `chi_sim` 和 `eng`。

OCR 结果会标记为：

```text
source_method = pymupdf_ocr_words
```

不会与原生 PDF 文本混淆。

## GUI 启动

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

或双击 `run_gui.bat`。

GUI 新增：

- 单 PDF：`Fast Index（推荐）` / `全页深度解析`
- 单 PDF OCR：关闭 / 自动 / 强制
- `批量项目` 页面
- 多 PDF 上传与公司/年份编辑
- 并行进程数
- 指标多选
- 批量 Excel / CSV 输出

## CLI 批量示例

```powershell
python batch_cli.py .\中国人寿2024.pdf .\中国平安2024.pdf `
  --metrics 总保费 净利润 核心偿付能力充足率 综合偿付能力充足率 `
  --ocr-mode off `
  --workers 2 `
  --output-dir batch_output
```

自动 OCR：

```powershell
python batch_cli.py .\A.pdf .\B.pdf `
  --metrics 总保费 核心偿付能力充足率 `
  --ocr-mode auto `
  --ocr-language chi_sim+eng `
  --workers 2
```

## 缓存

```text
workspace/cache/<PDF_SHA256>/
├── fast_index_<config>.json
└── deep_pages/
    ├── v4.3-deep-1_p00042.json
    └── ...
```

相同 PDF 再次查询新指标时：

1. Fast Index 可直接命中缓存；
2. 已经深度解析过的候选页也直接复用；
3. 仅补解析新增候选页。

## 批量输出

`batch_long.csv`：每个公司 × 年份 × 指标一行，保留来源和审计字段。

`batch_wide.csv`：指标为行，公司+年份为列，适合横向比较。

`batch_results.xlsx`：
- `long`
- `wide`

每个单元格对应的来源证据在 long 表中保留：
- source PDF
- SHA256
- page
- matched label
- source_method
- confidence
- L0/L1/L2 status
