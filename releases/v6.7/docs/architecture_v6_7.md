# v6.7 架构说明

## Registry 边界

- Metric Registry：指标语义。
- Table Family Registry：结构化采集目标、成员、签名和策略。
- Research Definition：将表族、研究口径和版本固定到 Research Batch。
- Mapping：`Metric → Family → Member → Row Path`，不把表格误当单一指标。

## Discovery

`GenericDiscoveryService` 按策略插件运行：主表多附注、单项附注、直接附注表族、直接披露搜索。没有可靠签名时输出 `REVIEW_REQUIRED/UNRESOLVED`，不会制造表或金额。

## 输出

`Canonical Research Long` 是主真相，保留来源行、口径和审计字段。CSV 宽表用 `COL_xxxxx`，通过 `column_dimensions.csv` 恢复维度；Excel 用多行观察维度头。

`VisibleHeaderDimensionPolicy` 以唯一值计数决定展示：报告年和数据年始终可见；单值公司、口径、期间、币种/单位进入元数据；多值维度上升为 Header Level。重述在有区分时单独显示，否则可作为数据年后缀。

## 学习层

历史认证、拒绝和覆盖持续保留。当前只使用确定性特征排序与分层回退；ML/LLM 只能排序候选，不能生成金额、来源或直接认证。
