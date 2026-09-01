# AXA_research Golden Lite — 中国太保合并金融投资主表页面锚点 v1.0.0

推荐安装路径：

`C:\dev\AXA_research\golden_corpus\v1.0.0\discovery_page_anchors\cpic_consolidated_financial_investment\`

不要放入 `releases`、`DATA_HOME` 或 `output_agent_runs`。

本包只验证固定 PDF 中“中国太保（合并）金融投资主表”的页面定位：

- 2023 年报：PDF 阅读器第 74 页
- 2024 年报：PDF 阅读器第 73 页
- 2025 年报：PDF 阅读器第 74 页

它还验证目标口径为合并、目标报表为合并资产负债表、目标研究表族为金融投资，以及图像型/低文本层页面必须触发现有 Conditional OCR。

它不证明 OCR 已正确读取全部文字和金额，也不证明成员、子表、Canonical 或 Merge 已完成。

当前状态为 `HUMAN_VERIFIED_PENDING_SHA`。Codex 需要在 `C:\dev\AXA_research\docu` 中定位三份 canonical PDF，计算 SHA256、确认页数与页码体系，再升级为 `CERTIFIED_GOLDEN`。在 SHA 绑定前，这些断言只用于诊断，不应阻断 Release。
