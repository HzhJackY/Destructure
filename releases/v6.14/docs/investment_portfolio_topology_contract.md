# 投资组合 Registry 拓扑与离线执行合同

状态：`ACTIVE_FOR_INVESTMENT_PORTFOLIO_V2 / PING_AN_OFFLINE_BASELINE_ACCEPTED`

合同版本：`INVESTMENT_PORTFOLIO_TOPOLOGY_CONTRACT_V2`

## 核心语义

`investment_portfolio` 表示公司直接披露或可由正式主表—附注链接证明的投资组合来源资产，
不是 `financial_investment` 的别名。Family 没有跨所有来源都成立的物理必需成员；必须先认证
披露拓扑，再决定成员适用性和审核规则。

| 拓扑 | 适用成员 | 来源总额规则 | 已观察样本 |
|---|---|---|---|
| `DIRECT_SEPARATE_TABLES_SAME_PAGE` | category + measurement | 来源披露总额必需 | 平安 2023 |
| `DIRECT_COMPOUND_TABLE` | category + measurement | 来源披露总额必需 | 国寿 2024–2025、太保集团 2023–2025、新华 2023–2025 |
| `DIRECT_SINGLE_AXIS_TABLE` | category；measurement 不适用 | 来源披露总额必需 | 国寿 2023 |
| `MULTI_NOTE_COMPONENT_SET_NO_REPORTED_TOTAL` | portfolio_components | 禁止合成总额 | 未来/负向拓扑；当前上市母公司样本未观察 |
| `HYBRID_DIRECT_AND_NOTE_COMPONENTS` | 直接块和组件集合均可存在 | 只能使用直接披露总额 | 本轮未观察 |

## 资产身份

- 两张独立物理表即使同页、同总额也保留两个资产 ID。
- 一张复合表按 `CLASSIFICATION_AXIS_TRANSITION` 形成两个逻辑块，同时共享一个物理表 ID。
- 多个附注各自保留 `CertifiedChildTableLink` 和 Capture 身份；`portfolio_components` 只是集合身份，不能吞并子表。
- 分类轴之间禁止合表；来源没有披露的轴应为 `NOT_APPLICABLE`，不是 `MISSING`。

## 抓取和认证边界

1. 原生文本先定位直接披露表。
2. 直接表不存在时，复用正式主报表解析定位候选组件。
3. 组件只能通过 `CertifiedChildTableLink` 进入现有 Whole-table Capture。
4. Stage A 认证拓扑、来源身份、页范围、期间、单位、轴和披露总额状态。
5. Stage B 认证每个物理表或附注子表；不存在统一固定成员集合。
6. Golden 只能比较已注册的同 Family、同拓扑断言，不能回填机器证据。

## 五拓扑共享执行计划（节点 1–6）

UI 与离线调用方必须共同消费 `PORTFOLIO_TOPOLOGY_EXECUTION_PLAN_V1`；两者不得再根据
`statement_type` 或按钮位置各自猜测 Stage B 路由。执行计划只投影 Discovery 证据，不执行
认证、持久化或 Capture。

| 拓扑 | UI/离线路由 | Stage B 认证目标 | 聚合政策 |
|---|---|---|---|
| `DIRECT_SEPARATE_TABLES_SAME_PAGE` | `DIRECT_ONLY` | 每张 `DIRECT_PHYSICAL_TABLE` | 两个物理资产保持独立 |
| `DIRECT_COMPOUND_TABLE` | `DIRECT_ONLY` | 一个物理 ROI、多个逻辑 block | 一物理表、两逻辑轴 |
| `DIRECT_SINGLE_AXIS_TABLE` | `DIRECT_ONLY` | 一个物理 ROI | 未披露轴为 `NOT_APPLICABLE` |
| `MULTI_NOTE_COMPONENT_SET_NO_REPORTED_TOTAL` | `NOTE_ONLY` | 每个 `NOTE_CHILD_TABLE` | 组件独立，禁止合成总额 |
| `HYBRID_DIRECT_AND_NOTE_COMPONENTS` | `HYBRID` | Direct ROI 与 Note 子表链接均必需 | 只承认 direct 总额；note 不重复计入 |

五类最终仍物化为既有 `CertifiedChildTableLink`，随后进入唯一 Whole-table Capture 主干。
Direct 来源不伪造附注 Anchor，Note 来源不得绕过子表认证；Hybrid 任一必需分支缺失时不得
生成 Capture Plan。

## v6.13 节点 4–8 实现结果

- `INVESTMENT_PORTFOLIO_V2` 已通过现有 Generic Discovery 调度
  `DIRECT_PORTFOLIO_TABLES`，原生文本优先，未新建平行管线。
- 10 份上市母公司年报均识别为直接披露拓扑：平安 2023 为同页双表，国寿 2023
  为单轴表，其余 8 份为复合表；10/10 页码、拓扑、适用轴、物理资产数量和披露总额
  与 Golden 匹配，`ocr_used=false`。
- Stage A 使用投资组合专属拓扑/Golden 合同；不会调用金融投资的
  `fvtpl_assets` 等固定成员门禁。
- Stage B 对每个物理资产生成 `DIRECT_PORTFOLIO_WHOLE_TABLE` 认证链接；物理 ROI、
  页码、标题、资产 ID 和行边界均为硬门禁，不执行金融附注检索或附注列签名校验。
- 平安 2023 基准已完整运行 Discovery → Stage A → Stage B → Whole-table Capture →
  CaptureDecisionReducer → Canonical Long → Merge → User Research XLSX。两个 Capture
  均为 `SUCCESS/merge_ready`，30 行机器结果与逐行 Golden 全匹配。
- `INVESTMENT_PORTFOLIO_V1` 保留兼容身份但不再作为默认可选项；既有历史资产不回写。
- `ChildCaptureExecutionService` 从持久化 occurrence 重建 plan 并校验 required links；
  headless 调用不能绕过 UI 门禁。
- 太保集团 2023 的 `DIRECT_COMPOUND_TABLE` 已完成 native-text 真实 Capture：一个物理
  job 物化 `BY_INVESTMENT_OBJECT` 与 `BY_ACCOUNTING_MEASUREMENT` 两个独立逻辑 Capture。

## 明确未执行

- 按用户要求未运行浏览器 E2E。
- 未运行 OCR；当前 10 份直接披露样本均由原生文本定位。
- Note-only 与 Hybrid 已完成 synthetic/service-contract acceptance；由于当前上市主体样本均为
  direct 拓扑，尚不宣称这两类已完成上市公司真实 PDF 验收。
- 浏览器 E2E、后续 Canonical/Merge/XLSX 本轮未运行。
