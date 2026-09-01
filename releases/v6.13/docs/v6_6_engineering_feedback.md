# v6.6 工程反馈

## 已验证的改进

- v6.6.x 已重新接入 note-aware Table Boundary Resolver。中国平安 2025 年报附注八-9至八-12分别在下一附注标题前精确终止，四张表均未跨入后续附注。
- 修复前四张表全部退化为 `max_pages`，共发现 28 条说明关键词文本被误列为 `DETAIL`；修复后为 0，混合文本金额单元格为 0。
- Certified Capture 实际调用链现在为：Certified Note Target → Boundary Resolver → Table Region → Header Resolver → Semantic Row Classifier → Structured Extractor → Reconciliation。
- 中国平安 2023—2025 三份真实 PDF 在隔离 DATA_HOME 中完成 3 个主表 Anchor、12 个认证附注明细抓取作业；作业无 `FAILED`。
- 认证目标以 `CERTIFIED_NOTE_TARGET` 约束作业；未选 Anchor、仅候选页或无认证页均不能被 worker 扩展为全文抓取。
- 审核页面改为研究任务视角：一个来源 PDF 的主表与全部已认证子表一起展示，而不是把底层机器候选伪装为当前任务的待审核项。
- 已实现 `IMPLICIT_TOTAL_ROW_RECOVERY`：中国平安 2025 年报附注十二中“上市 + 非上市 = 无标签 609,550 / 356,493”被保留并恢复为可审计的隐式总额；PDF 原始标签仍为 NULL。
- 研究任务审核页现在可直接审核已完成 Capture 的列维度与表边界；不再要求为这两类结构审核跳转至“数据资产管理”。
- “重跑范围”现按认证目标生成版本化重跑计划并实际提交新作业：`REVIEW_REQUIRED` 与 `ALL` 不再错误调用仅处理 `FAILED` 作业的旧重试接口。

## 真实代码审计结论

1. 旧 Guided runner 只传递了 `start_page_override`，没有在 CaptureService 层验证该页来自认证目标；这正是“已经定位却全部失败/跑偏”的关键风险。v6.6 已在 Service 和 worker 两层封闭此路径。
2. 原计划执行代码把 `MetadataRegistry.connect()` 这个上下文管理器当作 SQLite connection 使用；认证后更新作业 payload 会抛错。已修正为 `with` 上下文。
3. 旧结果审核通过名称和模糊批次关联作业，导致主表/子表/历史候选混杂。v6.6 用 `capture_plan_id + plan_member_table` 写入作业 payload 并据此回链。
4. 研究任务回收站此前只改变计划状态，并未处理已生成的 Capture；现在会调用资产服务移动/恢复下游 Capture。合并项目仍应以 Capture 生命周期为准重新检查依赖。
5. `extract_statement_anchor` 对“金融投资”仍是高质量参考实现，而不是完整的通用结构解析替代品。通用连续子项解析器已有接口，但更多报表类型仍需真实样本扩充。
6. 合表页过去直接扫描 `table_captures` 文件夹，而资产管理页读取 SQLite，因此旧目录会出现“待认证但没有 Capture”的假象。v6.6 已改为以活动 SQLite Capture 为唯一合表候选来源。
7. Boundary 失效的直接原因是 Guided 传入完整引用 `附注八-9`，旧 spatial resolver 仅在参数为纯数字时计算 `next_no`，导致正确起始页之后按 `max_pages` 抓取。现在由统一 ordinal parser 处理完整引用和常见编号格式。

## 对业务设计的判断

“Statement Anchor + N Note Detail”是正确的财报研究模型：它保留主表金额、口径和附注入口，也使附注明细能独立审计。边界在于一份年报可能同时存在合并、公司、分部或监管口径；当多个 Anchor 都完整时，系统必须允许双口径并存，不能仅按“合并优先”静默覆盖。

批量审核应只操作已聚类、同一 Anchor 下的子项；跨公司或跨口径的批量确认只能作为高置信建议。人工 ACCEPT、REJECT、OVERRIDE 都应保留为训练样本，但不能直接把历史页码或附注号当作下一年事实。

## 已知限制

- 扫描件或不可检索 PDF 没有 bbox 时只能显示 Level 3 页级证据，仍需人工审核。
- 未发现下一同级标题时 resolver 保守返回 LOW confidence，并要求人工审核；不会宣称硬边界成功。
- 视觉横线/空白只能作为辅助证据，不能单独覆盖明确的附注标题边界。
- `REVIEW_REQUIRED` 表示需要结构审核的完成结果；系统仅在该状态或用户选择 `ALL` 时创建新的受认证目标约束的重跑计划。它不会把该状态误报成 worker 失败。
- Family Merge 目前在 Capture 完成后可从研究任务进入，但跨年、跨口径的研究定义仍需用户确认，不应自动混合。
- 隐式总额的首版只在连续、可数学验证的 breakdown 后恢复；无法勾稽的无标签数值行保留为 `IMPLICIT_ROW_CANDIDATE`，不会自动命名。

## 本次 v6.6 收口审计：状态、预览与注册一致性

### 根因与实际修复

1. `HARD_BOUNDARY_CONFIRMED` 与 `REVIEW_REQUIRED` 同时出现，并非已恢复的空标签合计行天然不可用。真实 24 个最新 Capture 均显示硬边界、自动表头、无混合单元格、一个已恢复 `IMPLICIT_TOTAL` 且 `merge_ready=True`。误显示的根因是结果页把不可变的历史 Job 状态当成当前 Capture 质量。现在 `execution_status` 与 `capture_quality` 分开投影，重跑与合表只消费最新活动 Capture 的实时质量。
2. `raw_item=NULL` 只有在没有认证行角色、仍携带数值时才是阻断项；`row_role=IMPLICIT_TOTAL` 是合法、可审计的结构恢复。无法勾稽的匿名数值行仍保持 `IMPLICIT_ROW_CANDIDATE` 并阻断。
3. 真实三年测试首次暴露 12 个 Job 全部成功但 1 个 Capture 未注册。原因是并发 worker 同时写 SQLite/批次摘要，旧桥接层吞掉异常后仍让 Job 标成 SUCCESS。同步现已串行化、重试、记录失败事件；CaptureService 会验证注册记录，不允许“孤儿成功”。
4. 审核预览过去假定页码与 PNG 永远可用，历史 NaN、页码越界或 PDF 不可打开会直接使 Streamlit 崩溃。`page_preview` 现在返回结构化状态，所有审核入口统一安全渲染；只有存在真实下一附注证据时才显示“终止证据”，搜索窗口截止页不再冒充边界。
5. 合表之前只依赖 UI/SQLite 的 `merge_ready`，旧索引可能让待审 Capture 混入。MergeService 现在重新读取 `table_capture_result.json` 并实时计算质量，形成不可绕过的第二道门禁。

### 架构判断

- 单一当前质量模型是必要的：Job 表示一次执行是否结束，Capture 表示当前证据能否用于研究，两者不能共用一个状态字段。
- `Statement Anchor + N Note Detail` 仍是合理主模型，但通用解析必须继续保留多口径 occurrence；合并/公司/监管口径都完整时应并存，由研究定义选择，不能靠固定优先级静默覆盖。
- 批量审核只能减少点击，不能减少审计粒度。每个年度、每个成员仍需独立 adjudication/training example；否则一次错误批量选择会污染公司历史模板。
- PDF 预览是审核证据，不是认证本身。只有 bbox、标题身份、附注序号和边界证据一致时才能自动确认；扫描件页图仍需 OCR 或人工判断。

### 仍需管理的技术债

- `extract_statement_anchor` 对“金融投资”是经真实样本验证的参考策略，不等于任意 `display_name` 的通用视觉结构解析器。
- Streamlit 页面仍承担较多流程编排；后续宜把预览模型、审核命令和 Capture 状态投影继续下沉到 Service，以便无界面回归。
- 全量 Registry Rebuild 仍是恢复工具而非在线事务协调器；在线路径应继续使用增量同步和明确错误事件，避免频繁全目录重建。
- 扫描型或字体编码异常 PDF 目前只会保守降级，不能宣称 bbox 级认证。

## 后续改进建议（不改变 v6.6 完成状态）

1. 在研究任务审核页显示同一认证目标的新旧重跑结果差异，帮助用户决定是否保留新 Capture。
2. 用真实多公司年报扩展通用 Anchor/连续子项解析，逐步降低“金融投资”参考策略的占比。
3. 引入 Capture 语义质量评分（标题、附注、页码、表边界、主附对账）后再允许一键 Family Merge。
4. 为扫描型 PDF 增加 OCR bbox 管线，避免只能依赖页级预览。

## v6.6.x 来源感知 Member Table 合并热修复

### 真实根因

此前 `family_merge_v63.py` 已有较完整的表族身份设计，但研究引导抓取实际调用的是 `MergeService → table_merge.py` 的旧合表路径。该路径的 `canonical_key` 和分组维度没有包含 `member_table/member_table_role`；同时 Guided Job 仅在 payload 保存 `plan_member_table`，`CaptureService` 没有把该字段写进 Capture 元数据。因此同一财报中不同附注明细表的同名行被错误送进同一金额冲突比较。

### 修复判断

这不是 UI 警告问题，必须在 Capture、Service 和 Merge 三层修复。现在：

- 新 Capture 把表族、子表、角色、来源主表、附注号和子表顺序写入 `capture_metadata.json`；
- MergeService 对历史 Guided Capture 可从 Job payload 和 Capture Plan 恢复这组来源证据；
- 旧合表引擎以来源语义 + 行路径 + 完整列维度建立观察身份；
- 缺失来源身份的记录只进入 `REVIEW_REQUIRED_SOURCE_IDENTITY`，不会因金额不同伪报冲突；
- 最终宽表、结构顺序及来源身份 QA 都保留用户可读的表族/子表层级。

### 真实验证与边界

中国平安 2023 金融投资 4 张附注明细表形成 93 个来源感知行身份。按旧的忽略子表身份模拟，会产生 24 组假冲突；修复后真实 `VALUE_CONFLICT=0`。政府债、金融债在 FVTPL、债权投资、其他债权投资中各保留 3 个来源；总额类行保留 4 个来源。独立合成回归也证明：同一子表、同行路径、同完整维度但金额不同仍为 `BLOCKING VALUE_CONFLICT`。

仍需注意：若历史 Capture 的元数据和原始 Job payload 都不含子表身份，系统不能凭同名行猜测来源，应保留待审核状态。跨年或跨公司合并也不应因“金融投资”同名而自动视作同一研究口径。
