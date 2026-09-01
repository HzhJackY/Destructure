# v6.0 Update

新增独立数据资产管理中心、Capture/Batch/Merge 批量生命周期、失效来源依赖保护、整批重新抓取，以及 Single-Instance Launcher / 重启 / 退出控制。v5.9 双表头解析与全部回归门槛继续保留。详见 `README_V6_0.md` 与 `DATA_ASSET_MANAGEMENT_GUIDE_V6_0.md`。

# v5.9 Update

新增 Classic + v5.7 Generalized 双表头解析器、独立数值列裁判、自动仲裁、人工算法选择与安全 KEEP/DROP 列拓扑复核；修复标准4列被重复识别为8列的回归，并将 v5.7/v5.8 已解决案例固化为发布回归门槛。详见 `README_V5_9.md`。

# v5.8 Update

正式修复合表期间维度：本年/本期转换为年报实际年份，去年/上年/上期转换为实际年份-1；原始文字保留在 `source_period_label`。同时修复 v5.7 将相对期间误当 `document_year` 的根因，并支持旧 Merge 重新物化时自动修复。详见 `README_V5_8.md`。

# v5.7 Update

修复“本年累计数/上年累计数”相对期间表头、无编号正文定位、换行科目/空值明细结构，以及“小计 + 减项 → 合计”的复核公式。详见 `README_V5_7.md`。

# v5.6 Update

新增共享 DATA_HOME 与历史版本迁移中心；支持从实际定位标题自动反推附注编号；parent_section 改为同表重名时才参与身份消歧；新增合计/小计 Warning-only 算术复核。详见 `README_V5_6.md` 与 `DATA_MIGRATION_GUIDE_V5_6.md`。

# v5.5 Update

修复本集团/本公司等父级表头跨多个年份列时 scope 丢失导致的假 VALUE_CONFLICT；新增列维度唯一性硬闸门与表头维度人工复核，可修改 year/scope/restated 后重新物化正式输出。详见 `README_V5_5.md`。

# v5.4 Update

合表新增严格结构顺序契约：用户选择排序基准表，`canonical_order` 保证小计/明细/合计不被 groupby/pivot/字母排序打乱；其他来源独有行按上下文插入并输出顺序冲突审计。同时新增 Merge Library 管理、软删除、回收站恢复和永久删除。详见 `README_V5_4.md`。

# v5.3 Update

新增输出结果内直接选择最后有效记录的边界人工复核；历史整表升级为 Capture Library，支持来源感知命名、预览、重命名/备注、软删除/恢复；未确认边界的抓取禁止进入正式合表。详见 `README_V5_3.md`。

# v5.2 Update

候选选择升级为“语义分 + 证据质量 + 综合裁决分”，解决多个1分来源误选缺单位证据；新增CSV自定义保存目录和文件名。详见 `README_V5_2.md`。

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
