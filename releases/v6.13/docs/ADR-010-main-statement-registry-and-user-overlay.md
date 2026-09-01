# ADR-010 — 主报表 Registry 与 DATA_HOME 用户 Registry 覆盖层

状态：ACCEPTED（v6.13 开发候选）

## 背景

既有 Registry 只含“金融投资”和“投资组合”。中国人寿、中国平安 2023–2025 年报的
合并资产负债表和合并现金流量表均可由原生文本稳定定位，但它们不是附注表，也不应被
伪装成附注目标或拆成相互重叠的现金流分区 Capture。

同时，底层 SQLite 已具备 Family、Member、Definition 表，却允许 UI 直接写入 ACTIVE
对象；草稿可能被旧查询误作为知识包，内置金融投资语义也可能被覆盖。

## 决策

1. 新增 `DIRECT_MAIN_STATEMENT_TABLE` Discovery Strategy，仍由同一
   `GenericDiscoveryService` 调度；它只使用原生 Fast Index，产生可审核的主表 Anchor。
2. 首批内置 Family 仅为 `consolidated_balance_sheet` 与 `cash_flow_statement`。每个均为
   单一 Whole-table Member，并保留合并口径、主表类型、页范围和 Registry 身份。
3. 主表整表在 Anchor 人工认证后，仍由 `ChildDiscoveryRepository` 物化
   `CertifiedChildTableLink` 和单段 `CertifiedChildTableSegment`；`note_table_inventory_*`
   明确为 `NOT_APPLICABLE_DIRECT_MAIN_STATEMENT`，不得伪造附注 inventory。
4. 用户 Registry bundle 先写入 DATA_HOME 的 `user_registry_drafts`。只有 service 校验
   Family/Member/Definition/策略/引用完整后，才在一个事务中提升为现有 ACTIVE 表。
5. 内置 Family、Member、Definition 在 service 层只读；Definition 的通用直接创建接口
   只生成 DRAFT。Generic Discovery 只接受 ACTIVE Definition。

## 后果

- 用户自定义 Registry、内置 Registry、批次与 Discovery 共用同一 SQLite owner 和正式
  Capture 链，不新增平行 OCR、Capture、Review、Canonical、Merge 或导出路径。
- 已固定在历史批次/资产中的 Definition 版本不回写；归档只阻止新的选择。
- `DIRECT_MAIN_STATEMENT_TABLE` 的整表分页通过认证 segment 的 `start_page/end_page` 表示，
  不把连续页误判为独立资产。
- Stage A 的 Golden Anchor 门禁必须按 Registry Family 显式选择。现有金融投资 Golden
  成员集不得因公司/年份相同而套用于投资组合、主表整表或用户 Registry；未注册 Golden
  契约的 Family 仍须按机器证据和原 PDF 完成人工审核。
- 经营/投资/筹资现金流分区、股东权益、保险合同余额并未在首版新增独立 Registry：前两类
  与整表 Capture 重叠，后者跨新旧准则，需要单独的版本化成员合同和证据矩阵。

## 2026-08-13 补充：投资组合拓扑合同与第一条离线基线

物理年报证据证明 `investment_portfolio` 不能把“按投资对象”和“按会计计量”设成跨来源
统一硬门禁。v6.13 最初登记 `INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT_V1`，随后以 V2
补齐五拓扑 UI/离线执行政策；两版均由拓扑决定
适用成员与必需成员，并明确禁止把多个附注组件自动求和为来源投资组合总额。

用户审核后已新增 `INVESTMENT_PORTFOLIO_V2`，由同一 Generic Discovery 调度
`DIRECT_PORTFOLIO_TABLES`。Stage A 使用 Family 专属拓扑/Golden 门禁；Stage B 按认证
物理 ROI 建立 `DIRECT_PORTFOLIO_WHOLE_TABLE`，不复用金融投资附注成员审核，也不建立
平行 Capture/Canonical/Merge 管线。

平安 2023 作为第一条正式离线基线，已通过既有正式路径到 User Research XLSX；10 份
上市母公司年报的直接披露定位矩阵也已 10/10 匹配 Golden。附注组件与混合拓扑仍保留为
未来扩展合同，不因当前全部样本是直接表而删除。

## 2026-08-13 补充：五拓扑 UI/离线共用执行计划

`PortfolioTopologyExecutionPlan` 是 Discovery 与认证之间唯一的拓扑路由投影。它把认证目标
显式分为 `DIRECT_PHYSICAL_TABLE` 和 `NOTE_CHILD_TABLE`；UI 与离线调用方读取相同计划，
不得自行按 `NOTE_SECTION` 推断下一步。五类最终仍物化为既有
`CertifiedChildTableLink`，不新增平行认证或 Capture 管线。

`HYBRID_DIRECT_AND_NOTE_COMPONENTS` 在同一 filing 计划内必须同时保留 direct 与 note 两类
必需目标；任一分支未认证则 fail-closed。只有 direct 来源披露总额可成为投资组合总额，
note components 保留独立资产及 reconciliation lineage，不得重复加总。

## 2026-08-17 补充：Stage B 终态计划的显式重新抓取

相同 plan/scope 的普通提交继续幂等恢复原执行。已完成的 Stage B 会话如需重跑，
必须由 UI 的明确“重新抓取当前逻辑表”动作创建新 execution-attempt session；新会话
保留原认证 plan/scope 快照，但使用新 Research Batch 和 source batches。非终态会话不允许
重复建批，预览/rerun 不得隐式创建尝试。
