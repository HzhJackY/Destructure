# 变更：CPIC 扫描主表 Anchor OCR 空间证据

修复中国太保扫描资产负债表中，已存在的 OCR BBox 金额/期间证据无法进入 Stage A Anchor 与 Golden 对照的问题。

变更仅建立 `anchor_amount_observations` / `anchor_period_observations` 的审核证据通道。它不改变 Golden 内容、研究定义、Capture Plan，也不会让 OCR 金额进入正式 Capture、Canonical 或 Merge。

真实 canary：`output/_agent_runs/cpic_ocr_anchor_evidence_fix/canary_stdout.txt`。
