# v5.1 Update

默认整表引擎升级为 Spatial ROI + Column Anchors，修复数字碎片、跨表头污染和抓取越界；新增完整“合表 / Taxonomy”工作区。详见 `README_V5_1.md`。

# v5.0 Update

新增“整表抓取 / Table Capture”工作区；支持附注明细整表、多层表头、跨页续表、原始行名/层级保留。详见 `README_V5_0.md`。

# Financial Metric Resolver v3 - PDF First

这是 v1/v2 的正式 PDF 版本。

目标对象不是 Excel，而是上市公司年报、季报、偿付能力报告等 **PDF 财报**。

核心架构：

```text
PDF
 │
 ├─ pdfplumber 结构化表格提取
 ├─ 坐标 words 行重建（表格失败时补召回）
 │
 ▼
L0 人工规则标准化
 │
 ▼
L1 候选行评分
  名称 + 别名 + 排除词 + 表类型 + 行位置 + 数值特征
 │
 ├─ 高置信度 -> 自动确定
 └─ 低置信度 -> 可选 DeepSeek / Gemini
                   │
                   └─ 只能从候选 candidate_id 中选择或 abstain
                        禁止生成金额
 │
 ▼
Python 确定性提取数值 / 单位 / 页码 / 上下文
 │
 ├─ results.json  机器处理
 ├─ audit.jsonl   审计追踪
 ├─ report.html   人工阅读（推荐）
 └─ report.md     人工阅读 / Git版本管理
```

## 为什么没有直接照搬“把候选表发给LLM，让LLM返回金额”？

参考方案的方向是对的：`pdfplumber -> 关键词过滤 -> LLM -> JSON + 表格片段`。

但生产级金融数据系统不应让 LLM 自由生成金额。v3 做了一个关键收紧：

- LLM **只选择候选行**；
- 页码、行文本、所有数字都必须先由 Python 从 PDF 原文提取；
- LLM 返回不存在的 candidate_id 会被代码拒绝；
- 数值与单位换算由 Python 执行；
- 多列期间无法唯一判断时，不强行伪造“最新值”，而是在人工报告展示全部数值并给 warning。

因此系统同时保留了参考方案的可用性和此前 v1/v2 的可审计性。

---

## 安装

```bash
python -m pip install -r requirements.txt
```

Python 3.10+。

## 最简单运行：完全不用 LLM

```bash
python financial_metric_pdf_resolver.py sample_financial_report.pdf \
  --metrics 营业收入 净利润 归母净利润 保险合同负债 \
  --rules metric_aliases.json \
  --output-dir demo_output
```

Windows PowerShell:

```powershell
python financial_metric_pdf_resolver.py sample_financial_report.pdf `
  --metrics 营业收入 净利润 归母净利润 保险合同负债 `
  --rules metric_aliases.json `
  --output-dir demo_output
```

## 本次查询临时增加别名

```powershell
python financial_metric_pdf_resolver.py 年报.pdf `
  --metrics 营业收入 净利润 `
  --alias "营业收入=营业总收入|主营业务收入" `
  --rules metric_aliases.json `
  --output-dir output
```

注意：过于宽泛的 `"收入"` 只适合做用户查询提示，不建议长期写入强规则别名。

## DeepSeek 兜底

```powershell
$env:DEEPSEEK_API_KEY="..."
$env:DEEPSEEK_MODEL="deepseek-v4-flash"

python financial_metric_pdf_resolver.py 年报.pdf `
  --metrics 营业收入 净利润 `
  --enable-llm `
  --llm-provider deepseek `
  --output-dir output
```

## Gemini 兜底

```powershell
$env:GEMINI_API_KEY="..."
$env:GEMINI_MODEL="gemini-3.5-flash"

python financial_metric_pdf_resolver.py 年报.pdf `
  --metrics 营业收入 净利润 `
  --enable-llm `
  --llm-provider gemini `
  --output-dir output
```

模型名均可用 `--llm-model` 覆盖，避免代码与供应商模型版本强绑定。

---

# 输出文件

## 1. report.html - 默认给人看

打开浏览器即可阅读。

每个指标会显示：

- 查询名、标准科目
- RESOLVED / REVIEW_REQUIRED / UNRESOLVED
- L0/L1/L2 决策层
- 置信度
- PDF 页码
- 匹配到的原始科目名
- 主值及期间上下文
- 所有数值列
- 原始单位与换算为元
- 指标所在行前后表格片段
- Top 5 候选
- 人工复核警告

## 2. report.md

适合 Git、实习项目记录、审计归档和直接阅读。

## 3. results.json

给后续 ETL / 数据仓库 / API 使用。不是主要人工界面。

## 4. audit.jsonl

每次指标解析一行完整证据链，适合追责和回放。

---

# PDF 提取策略

v3 同时使用两种本地解析：

### A. pdfplumber.extract_tables()

优先处理有真实表格线或可识别表格结构的年报。

### B. 坐标行重建

对 `extract_tables()` 失败、合并单元格复杂、无边框财报，使用：

```python
page.extract_words()
```

按照 y 坐标聚类成行，再按 x 间距重建单元格。

候选来自 B 时，人工报告会明确提示：

> 该候选来自坐标行重建，建议核对 PDF 原页。

---

# 扫描 PDF

pdfplumber 主要适合文本型 PDF。

如果某页：

- `extract_text()` 几乎为空；
- 目标表格实际上是扫描图片；

v3 会将其标记为：

```text
likely_scanned_pages
```

并在 HTML 报告显示“扫描页风险”。

本版本故意没有静默 OCR，因为 OCR 应该是独立层并保留 OCR 来源标记：

```text
PDF native text
    ↓ failed
OCR
    ↓
OCR candidate
    ↓
人工/LLM复核
```

不能让 OCR 结果和原生 PDF 文本在审计记录里混为一谈。

---

# 一个重要的数值安全规则

当一行有：

```text
项目 | 2025年 | 2024年
净利润 | 180 | 145
```

系统会尝试利用列标题判断 2025 是最新一期。

如果无法可靠识别：

```text
项目 | 180 | 145
```

系统不会谎称“180一定是最新一期”。

它会：

1. 在 `primary_value` 暂取最左数值；
2. `primary_value_confidence = LOW`；
3. 在 HTML/Markdown 显示 warning；
4. 同时展示 180 和 145 两列，供人工确认。

---

# 生产部署建议

下一步最值得增加：

1. OCR 独立层：PaddleOCR / OCRmyPDF，且保留 `source_method=ocr`。
2. PDF 页图裁剪：把命中表格所在区域直接截图嵌入 HTML 报告。
3. 多指标批处理与并行。
4. 报告日期/公司代码自动识别。
5. 单位和期间交叉验证。
6. 资产负债表恒等式、利润勾稽等财务 QA。
7. LLM 双模型一致性裁决，只用于高风险指标。
8. 人工“确认/驳回”反馈自动生成规则增量。
