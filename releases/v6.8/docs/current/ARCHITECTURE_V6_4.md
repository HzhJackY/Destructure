# v6.4 通用发现、审核与认证知识架构

数据流固定为：`Machine Discovery → Human Adjudication → Certified Discovery → Fast Path / Training Examples`。

- 任意 `display_name` 都可进入通用主表引导发现；预设仅补充候选词、优先报表和历史变体。
- `machine_discoveries` 为追加式机器证据；人工不会更新它。
- `discovery_adjudications` 记录 ACCEPTED、REJECTED、OVERRIDDEN、UNRESOLVED，以及操作者、理由和旧/新字段。
- ACCEPTED/OVERRIDDEN 产生 `certified_discoveries`，默认只作为同公司、同 filing type、同 statement type 的候选知识。
- Fast Path 复用标题、结构和定位策略，运行时必须重新验证主表、附注引用、目标标题及对账；页码和附注号不能盲用。
- 训练样本记录正例、负例和覆盖后的正确目标。ML 仅排序候选与给出置信度，绝不生成或覆盖财务数值。

分层知识回退顺序为：`Company → Filing Type → Statement Type → Table Family/display_name → Member Table → Historical Instances`，无同公司知识才回退至更泛层候选。

## 迁移

metadata registry 从 schema 2 增量迁移至 schema 3。新增 discovery、adjudication、certified knowledge 和训练样本表；旧 PDF、Capture、Merge、机器 JSON、Notes 不会被改写。迁移由 `MetadataRegistry.initialize_schema()` 幂等执行。

