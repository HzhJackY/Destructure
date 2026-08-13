# v6.9 Anchor Candidate Selection 与人工审核 Hotfix

## Anchor 选择

发现结果保持高召回，但在进入 UI 前按 PDF、口径、页区间、父行、bbox、
期间与附注证据去重。候选评分保存总分、分项、正负证据、硬门禁和算法版本。
系统仅在硬门禁全部通过、得分达到 0.85 且领先第二名至少 0.10 时，每个
PDF/口径最多预选一个候选。预选只是推荐；只有人工点击确认后才形成认证记录。

人工选择会追加写入 Anchor Certification Audit，并为选中项和替代项保存
`ANCHOR_CANDIDATE_V1` 正负训练标签。低置信或歧义候选进入审核收件箱。

## 人工审核中心

CaptureInspectionPanel 是唯一的单资产检查与审核入口。概览默认显示财务研究
人员可读的资产身份、来源、数据上下文、状态和阻断问题；原始 JSON 仅保留在
折叠的高级信息区。

审核由 Review Issue 驱动 Review Task。任务涵盖来源、PDF 边界、表块、表头、
行结构、最终数据列、单位/口径/期间、勾稽及最终认证。表头与行结构调整采用
结构化控件并创建不可变的新 Capture Version。任务裁决逐条追加写入
`review_task_decisions`。

最终认证必须同时满足任务完成与身份完整：研究定义、定义版本、表族、明确
口径和 current 版本缺一不可。Merge Eligibility 复用相同身份门禁，避免 UI
状态与合表资格漂移。

## 最终数据复核

最终数据复核展示原始表头到 Canonical 列的映射及 observation 来源，检测期间
交换、数据列数量不一致、年份 token 污染和最后一列映射缺失。机器证据不会因
人工裁决而被覆盖。

## 迁移

schema 11 只增加 Anchor 评分/认证、审核问题、审核任务和任务决策记录。迁移
幂等，历史机器证据保持不变。历史 `REVIEW_REQUIRED` Capture 可执行 reason
backfill；无法解释时使用明确的 legacy reason，而不是空白原因。
