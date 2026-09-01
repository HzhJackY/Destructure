# Incident Report INC-012: 三家公司子表跨表边界与垂直期间串期

## 1. 事发现象 (Symptom)

- 平安 2023–2025 与新华 2023 的债权投资在认证页末无法确认边界；早期补丁曾仅凭
  下一页的下一附注标题把它们抬为硬确认。
- 太保 2023 的 `12. 其他债权投资（仅适用2023年）` 因含两个数字 token 被当金额行，
  导致附注 11 抓入附注 12。
- 中国人寿 2023 持有至到期投资把同一年度的 `摊余成本/公允价值` 压成一列并串接金额，
  同页 2022 下半块又被写回 2023 列；跨页时第二期间列 offset 还会归零。
- 中国人寿完整页脚进入分块，形成边界、terminal 或 footer-only child 污染。
- 新华奇数页顶部运行页眉把公司名、报告年份和印刷页码排在同一原生文字行；年份与
  页码同时落入一个金额 anchor，导致 `MULTIPLE_NUMERIC_CLUSTERS_IN_ONE_CELL` 在正常
  fail-closed 门禁处中止 Capture。
- 中国人寿 2023 可供出售金融资产补充表的第三金额车道披露“`不适用`”；旧 token
  物化器只接受数字与破折号，导致该已占用槽位消失，行宽 `[2,3]` 被误判为缺列。
- 新华 2023 p188/p189 的 ECL 补充表把单独位于叶标题上一行的 `第三阶段` 裁出本地
  header bbox；第三列只剩“整个存续期预期信用损失－已减值”，与 Golden 列身份不一致。
  同时，稀疏三命中表头行的无界 Voronoi 分区会把第三列子标题复制到第四列 `合计`。

## 2. 根本原因分析 (Root Causes)

- peer-note 金额过滤器没有区分“年份限定标题”和真实多数字金额/账龄行。
- CertifiedChildTableLink 的 `end_page_hint` 被同时当作边界搜索上限；随后只读前瞻又未
  检查下一附注标题之前是否仍有续表表体。
- Classic header 允许 `1 leaf / 2 numeric clusters` 继续运行，measure 未进入列身份。
- stacked period 检测仅扫描首页且续页强制清空 section，导致 active offset/block 丢失。
- 完整年报页脚没有统一 layout-noise 排除语义，Header Review 与复合分块消费字段不一致。
- 既有完整年报页脚标记发生在金额行解析之后，无法阻止顶部运行页眉先进入
  `_line_to_spatial_cells()`；同时既有正则未覆盖“公司名 + 2024年年度报告 + 页码”版式。
- stacked vertical-period 路径在发现两个逻辑 block 后跳过了物理段规划；补回共享物理段后，
  逻辑 `block_id` 又被错误当作物理段 ID，导致认证 manifest 虽可验证、Scope materialization
  仍找不到可选 block，报 `CERTIFIED_LOGICAL_TABLE_SEGMENTS_REQUIRED`。
- `parse_number()` 虽已把“`不适用`”定义为非数值，但金额车道 token 筛选在调用它之前
  就丢弃了中文占位文字；topology 因而只能看到真正缺失的 cell，而非显式非适用证据。
- supplementary 本地 header 起点只接受同时命中至少两条金额车道的行，未把紧邻其上的
  单车道 group header 视为同一多级表头；多 parent hit 的 Voronoi 分配又缺少本地
  lane-gap 距离门禁，导致未覆盖车道被最近 hit 远距离填充。
- Guided runner 曾把 filing 级 logical-table union 回填到每个 request，使
  `PRIMARY_ONLY` 携带 supplementary 选择、独立 supplementary request 携带彼此 ID；同时
  bundle version 与 LogicalAsset 未完整区分 container、认证 logical table、scope、request
  和 root，重放时可能遗留旧 child 顺序并让 Merge 面对不唯一的 root 身份。

## 3. 正式修复

- 年份限定标题仅在明确 note ordinal + 标题语义下豁免；账龄、金额及占位符行保持拒绝。
- 认证页外只读 lookahead 不扩大 Capture ROI；标题前出现表体/金额时记录
  `LOOKAHEAD_PREFIX_CONTAINS_TABLE_OR_BODY_CONTENT` 并拒绝硬确认。
- header undersegmentation fail-closed；支持 measure 列并按 period+measure 唯一化。
- 全 ROI 构建 vertical period plan，跨页继承或切换正确 group offset/block；重复表头复用
  已存在 group，声明的空 measure 列仍保留。
- 页脚原始行保留且标记 `excluded_from_table_logic=true`；拓扑、勾稽、terminal、分块和
  Header Review 均消费同一排除字段。
- 金额 token 物化器在既有 lane anchor 与容差内接收“`不适用`/`N/A`”显式占位；标签区
  同词不进入金额单元格。Compound topology 将其与破折号同样标记为 `PLACEHOLDER`，
  保留 raw token 且不解释为零；未对齐文字和真实缺 token 仍 fail-closed。
- 本地多级表头从第一条 dense leaf header 向上吸收紧邻、无叙述标点且对齐金额车道的
  sparse group header；单命中若明确贴近一条 lane 仅绑定最近车道，多命中 Voronoi
  另受本地 lane-gap 距离门禁约束。该规则保留国寿分组 parent→leaf 绑定，不按公司硬编码。
- 新增通用 page-chrome 前置分类：只有行文本具有年报/年度报告语义且 bbox 位于页面顶部
  或底部 8% 时，才在金额切分前记录为 `PAGE_HEADER_NOISE`/`PAGE_FOOTER_NOISE`；原始文本
  与 bbox 仍保存为排除行。真正表体中的多金额簇继续触发原 fail-closed 阻断。
- Stage B 新增持久化抓取范围：`PRIMARY_ONLY`、`PRIMARY_WITH_CONTINUATIONS`、
  `ALL_NOTE_TABLES`。`LOOKAHEAD_PREFIX_CONTAINS_TABLE_OR_BODY_CONTENT` 不再一律等价为
  边界失败：仅主表策略下，已确认 continuation 可形成显式 policy truncation warning；
  包含策略下必须解析 continuation relation，未决关系继续阻断。
- 新华 2024 债权投资页的两年余额表与四阶段信用损失准备变动表分别识别为
  `PRIMARY_TABLE` 与 `SUPPLEMENTARY_TABLE`；下一页披露的比较期四阶段表因 period 维度
  重置，继续作为独立 `SUPPLEMENTARY_TABLE`，不因标题“（续）”挂接 continuation，
  不横向拼接，也不按公司名分支。
- 新华 2025 p197 的 2025/2024 信用损失准备区块位于同页、共享披露目的与四阶段金额轴，
  因此合并认证为一张 `SUPPLEMENTARY_TABLE`；period 重置不得单独触发逻辑表拆分。
- 新华 2025 主表页曾被误作附注候选。修复后 locator 与 Discovery 都执行
  `candidate_page <= main_statement_page` 拒绝，且 Tier 2/3 fallback 不能重新引入该页。
- `stage_b_execution_sessions.capture_scope_json` 随 registry schema 12→13 幂等补列；
  旧 `{}` 和旧 CaptureRequest 默认 `PRIMARY_ONLY`，提交后的 scope 冻结。
- 正式 Merge 不再把调用方传入的 bundle root 列表误当完整 Capture 清单；每个 root 先按
  registry `child_order` 展开全部 `CAPTURED` child，并对 bundle、认证 logical table、
  family/member、PDF ID/SHA256 与 `table_block_id` 做交叉核验。所有资产保留在 lineage，
  只有明确标记为非 SOURCE 的派生 observation 才按 row/cell 证据排除；原始 Capture graph
  不被改写，排除清单进入 Merge manifest。
- Guided self-selection 收口为：`PRIMARY_ONLY selected_logical_table_ids=[]`；每个
  `SELECTED_NOTE_TABLES` request 只携带自身 certified logical-table ID；filing union 只核验
  用户显式选择的 supplementary 集合，不再向每个 request 传播。
- CaptureBundle immutable version identity 纳入 note container、certified logical table、
  scope signature、CaptureRequest 与 root Capture；LogicalAsset identity 纳入 certified
  logical table 但排除 scope。bundle children 在同一事务替换并重建连续 `0..n-1` 顺序；
  Merge 严格要求每个 bundle 唯一 `child_order=0` root。

## 4. 验证结论 (Verification Results)

- 新增合成回归覆盖年份标题、账龄占位、lookahead 续表前缀、header round-trip、
  ordinal 勾稽、空 measure 列、excluded footer terminal 与跨页 vertical period。
- 真实 PDF Canary 覆盖太保 2023、平安 2023、中国人寿 2023 持有至到期投资和贷款。
- 新华真实 PDF Canary 覆盖 2023 债权投资及 2024 交易性金融资产、其他权益工具投资；
  三个运行页眉均在金额解析前排除，且保守多金额簇合成 invariant 保持通过。
- 新华 2023 p188/p189 真实 PDF Canary 精确验证第三列 measure 包含 `第三阶段`，第四列
  仅为 `合计`；最终代码 fresh `SELECTED_NOTE_TABLES` 为 6/6 SUCCESS、review=0、
  execution/quality pass，正式 DATA_HOME SHA256 保持不变。
- 最终正式 Stage B 复跑矩阵与合法治理阻断记录在本任务 Change Report。
- typed request/session persistence、重启恢复、reducer 与策略过滤回归分层记录；真实
  Streamlit 浏览器操作及最终 policy 全链复跑若未执行，必须明确标记 `NOT_RUN`。
- 四公司认证矩阵工具默认仍只运行 Discovery/Inventory/自动认证；显式
  `--execute-stage-b` 时才在同一隔离 scratch registry 上按 filing 调用
  `ChildCaptureExecutionService.create_execution_batch()`。工具以 scope contract v2 输出逐
  job request/capture/logical-asset lineage、certified manifest drift、Reducer blockers/warnings，
  并分开汇总 `execution_pass` 与 `quality_pass`。完整 49-job 矩阵不作为本次最终门槛，
  采用受控分批复跑；结果见下方追加验证。
- 12 份年报正式 fresh Merge 接收 49 个 bundle roots，展开 90 个 Capture assets；raw graph
  numeric 902，经 24 个非 SOURCE observation 排除后 Canonical/Merge numeric 为 878，
  满足 `902 = 878 + 24`。current Golden v3 为 883 cells（878 numeric + 5 DASH），全部通过；
  90/90 source identity 完整，`VALUE_CONFLICT=0`，review/blocking conflict=0，正式数据库
  SHA256 前后一致。
- 六份已认证 supplementary filing 的正式 fresh Merge 接收 14 个 bundle roots，展开
  18 个 Capture assets；Golden 14/14 tables、322/322 cells（266 numeric、52 DASH、
  4 NOT_APPLICABLE）全部通过，Canonical amount cells 322/322，冲突与顺序冲突均为 0。
- 最终状态按覆盖层级分开：当前 certified scope 无 Stage B、Review 或 Merge 阻断；但
  `ALL_NOTE_TABLES` 仅新华 2024 为 `CLEAR`，其余 11/12 仍为 `PENDING`。认证 corpus 中
  true `CONTINUATION_SEGMENT` 为 0；Streamlit 用户路径未运行，状态保持 `NOT_RUN`。

### 追加验证（2026-08-04）

- stacked 物理段修复后，国寿 2023「持有至到期投资」p177 的两个期间逻辑 block 共用一个
  `PRIMARY_TABLE` 物理段；manifest `VALID`，无 drift。
- 受控真实 Stage B 仅重跑国寿 2023（5 个作业）：`5/5 SUCCESS`、`quality_pass=true`、
  `review_required=0`；其余公司/年份沿用同日已完成的受控结果，不再启动完整矩阵。
- 代码回归为 `36 passed`（含真实国寿 stacked 与 manifest/Scope 选择）；Streamlit 浏览器
  操作未执行，仍标记 `NOT_RUN`。

## 5. 后续注意

- 缺少 CertifiedChildTableLink 或认证页跨度未覆盖续表时必须停在治理/边界阶段，不能由
  Capture 强制认证。已认证目标只允许按持久化 scope 做受控同附注多页扫描；扫描结果
  必须由 segment relation 和下一附注边界约束，未决关系 fail-closed。
- 父子行或合计与子项不一致继续保存为 warning，不属于本 incident 的阻断条件。
