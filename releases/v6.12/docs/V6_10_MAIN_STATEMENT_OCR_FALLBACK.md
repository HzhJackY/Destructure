# v6.10 主报表候选发现：条件式 OCR Fallback

## 目的

该热修复只解决扫描型或图片型 PDF 中“合并资产负债表、合并利润表、合并现金流量表”等主报表候选页无法被文本层发现的问题。

OCR 只输出候选页文本，继续交给原有 `locate_primary_statements` 与后续评分、去重、人工审核链路处理。它不会提取财务金额，也不会改变任何机器抓取金额。

## 触发与范围

1. 先完成原文本层索引与原评分。
2. 若已有分数不低于 `0.85` 的目标主报表文本候选，直接结束，绝不 OCR。
3. 否则只从目录指向页、目录邻页、财务章节邻页、低文本混合页、图片主导页组成候选集合。
4. 默认最多 OCR 12 页，优先级排序后执行；若候选恰好覆盖多页全文，会截断最后的低优先级页面，避免默认变成全文 OCR。
5. 单页文件默认 abstain，避免将“条件式 fallback”悄然扩大为全文 OCR；可由以后经审核的策略单独处理。

默认配置位于 `conditional_statement_ocr.py::OCR_FALLBACK_CONFIG`，包括 150 DPI、`chi_sim+eng` 和 `full_document_ocr_enabled=False`。

## 审计状态

- `FOUND_HIGH_CONFIDENCE_TEXT`
- `FOUND_HIGH_CONFIDENCE_OCR`
- `OCR_CANDIDATE_REQUIRES_REVIEW`
- `OCR_COMPLETED_NO_QUALIFIED_CANDIDATE`
- `NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_AVAILABLE`
- `NO_HIGH_CONFIDENCE_TEXT_OCR_NOT_TRIGGERED_BY_POLICY`

审计记录包含 OCR 页、页面模态、触发原因、耗时、错误摘要、引擎标识和是否为避免全文 OCR 而截断。

## 兼容与限制

- 文本型 PDF 的既有发现路径不变。
- OCR 与文本同页证据会合并，不创建重复候选。
- 本热修复未新增 OCR 结果持久缓存；该能力会在实际批量使用证明 OCR 成本成为瓶颈后，再以文档 SHA、页码、引擎/配置版本为键加入，避免在当前热修复中扩大缓存失效面。
- 未宣称所有真实扫描年报都已验证。定向测试使用合成的图片型 PDF 和注入式 OCR Provider 验证触发、边界、失败和去重合同；生产环境仍依赖 PyMuPDF/Tesseract 可用性。
