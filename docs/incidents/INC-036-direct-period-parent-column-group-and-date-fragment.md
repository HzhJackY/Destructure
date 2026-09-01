# INC-036 — Direct 父期间传播与日期残片进入 measure

状态：`RESOLVED_TARGETED_AND_REAL_PDF_VERIFIED`

## 现象

国寿 2024–2025、太保 2023–2024、新华 2023 的既有离线结果曾出现逻辑成员身份漂移或
`PERIOD_COLUMN_SWAP_RISK`。太保 2024/2025 的原生表头可进一步物化出
`measure="月31日"`、`header_raw="2024 | 月31日"`；太保 2023 的四条 leaf lane 一度全部
继承为当前期，Capture 保持 `REVIEW_REQUIRED / merge_ready=0`。

## 根因

- 父期间只保存日期文字中心点，叶子列再以最近距离传播父期间，无法表达两行或多行表头的
  连续列组范围。
- PyMuPDF 将完整日期拆成 `2024 / 年12 / 月31 / 日`。旧脚注清理把半个 `年12` 尾部数字
  当作脚注，错误接受 `2024年12`；剩余 `月31` 又由独立叶子解析入口识别为 measure。
- 父期间解析与叶子 label 解析未共享“已消费 span”，因此上游已识别的日期文字可以在下游
  被重新复制。
- Capture Orchestrator 无条件用请求首成员覆盖物理作业拆出的认证逻辑成员，使复合表的
  `member_table_id` 可能漂移。

## 修复

- 期间 span 支持最多五个相邻 word，裸数字脚注只有跟在完整 `日/末/初/度` 后才可剥离；
  `2024年12` 不再认证为完整期间。
- 新增 V3 父期间列组证据，保存 anchor、group bbox、父/子行带、consumed spans、group ID
  和评分证据。
- 同行表头按左侧父期间优先、右侧惩罚回退；上/下层表头按连续列组分区，范围不稳定时
  fail-closed。
- 叶子解析先删除父期间 `consumed_spans`，日期或日期残片进入 measure 时以
  `PERIOD_FRAGMENT_IN_MEASURE_LABEL` 阻断。
- 太保“日期即金额 leaf、右侧为占比 leaf”的同行布局以日期命中的物理数值 lane 作为列组
  起点，再由下一个期间起点划分连续组；最终归属仍由正式 period-group resolver 裁决。
- Capture Service 和 Orchestrator 保留认证 axis→member 映射，复合表子资产不再继承请求首成员。

## 验证边界

- v6.13 全部定向测试 96/96；共享空间 Capture、状态链、认证子表与 Orchestrator 回归
  127/127。
- 全新隔离 DATA_HOME 真实 PDF：太保 2023–2025、国寿 2024–2025、新华 2023 共 6/6
  通过父期间列组审计。每份均为 1 个物理作业；日期残片、period/measure 冲突、member 漂移、
  `PERIOD_COLUMN_SWAP_RISK` 和非 merge-ready Capture 均为 0。
- 国寿 2024–2025、新华 2023 的 Capture Golden、Canonical、Merge、XLSX 全链通过。
  太保三年 Capture 均 `merge_ready=1`，Canonical/Merge/XLSX 3/3 成功；既有 Golden
  标签/续行差异仍单独保留为验收失败，未放宽或改写 Golden。
- 未修改 ROI、历史 Capture、生产 DATA_HOME、OCR 路由或 Golden 金额；未运行浏览器 E2E。
