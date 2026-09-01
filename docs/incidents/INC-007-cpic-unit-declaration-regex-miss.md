# Incident Report INC-007: 中国太保单位声明“均”字导致单位继承缺失

## 1. 事发现象 (Symptom)

中国太保 2023–2025 年报金融投资附注抓取（如 2023 交易性金融资产，PDF 第 169 页）在
评审队列中误报 HIGH「单位不确定」（`UNIT_UNCERTAIN`，提示“文档单位继承或列单位未确认”），
阻断认证。机器证据 `table_capture_result.json` 中 `unit=None`、
`document_context.unit=None`、`unit_source_page=None`。

## 2. 根本原因分析 (Root Causes)

- 太保年报单位声明写法为“（除特别注明外，金额单位**均**为人民币千元）”。
- `document_context_resolver.py` 的 `_UNIT_PATTERNS` 要求“金额单位”后紧跟“为/以”，
  中间的“均”字使两个正则全部失配。
- `CaptureDecisionReducer` 在 `evidence.unit` 与 `document_context.currency_unit` 均缺失时
  阻塞打 `UNIT_UNCERTAIN`，导致误报。
- 对照：新华 2023 声明“金额单位为人民币百万元”（无“均”），可正常命中。

## 3. 正式修复

- 两个单位正则允许“均”并增强空格兼容：
  `金额\s*单位\s*(?:均\s*)?(?:为|以|：|:)` 与
  `金额\s*(?:单位)?\s*(?:均\s*)?(?:为|以)`（后者含“除特别注明外”前缀与“列示”后缀）。
- `DocumentContext` 新增 `unit_source_text` 审计字段，保留原始命中文本与来源页。
- 不改变 CaptureDecisionReducer 门禁语义；真正无单位的证据仍被阻塞。

## 4. 验证结论 (Verification Results)

- 三层回归测试 20/20 通过（正则正/负例、太保 2023 第 169 页真实页头集成、决策门禁）。
- 真实 PDF Canary：太保 2023/2024/2025 三份年报均解析出 `unit=千元`、
  `currency=CNY`、`unit_source_page=抓取起始页`、`unit_source_text` 保留原始声明。
- 既有 golden 验收、金融投资边界、多表块抓取回归 37/37 通过。

## 5. 后续注意

- 平安/中国人寿若存在同类“均”写法，解析器已兼容；无需额外改动。
