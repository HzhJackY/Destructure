# INC-043 — 金融投资规范成员键造成跨物理行合成

状态：`RESOLVED_REAL_PDF_AND_FORMAL_MERGE_VERIFIED`

## 现象

- 中国太保 2023 主表同时存在旧准则长标签行与当前期“交易性金融资产”行。
- 旧逻辑把两行都归入 `fvtpl_assets`，再按规范成员键选择附注和金额，可能把附注 2、
  附注 10、26,560 与 581,602 跨行组合。
- 初版跨准则桥接未纳入分类轴和同名 occurrence，同一附注不同分类轴的“合计”被误报为
  `BRIDGE_AMBIGUOUS_SOURCE_SET` 或 `BRIDGE_WIDE_IDENTITY_CONFLICT`。

## 根因

1. `member_table` 被错误当作物理行关联键；它实际是列报概念，可在同页出现多次。
2. 当前期合法破折号被一律视为当前期激活，未结合整页是否存在明确新准则当前行。
3. 长 alias 的新旧成员消歧过早，旧准则候选在期间证据裁决前已经丢失。
4. 桥接键只包含项目与父路径，遗漏已认证 `classification_axis` 和同名 occurrence。

## 修复

- Evidence V2 保留所有物理 occurrence，附注、金额、BBox 与期间均按 `source_row_id` 绑定。
- 两遍裁决新旧制度：先保留同长 alias 候选，再结合当前期有效值、比较期值及整页明确当前行
  决定 `presentation_member_id`；旧行合法破折号可判为比较期旧成员。
- V6 Registry 为每个列报成员提供制度、分析桶、可比等级与显式桥接组。
- Canonical 保留桥接快照、认证拆分、分类轴、父路径和 occurrence；正式 Merge 生成双视图。
- 桥接键与宽表索引纳入分类轴和 occurrence；同期间多来源继续禁止求和。

## 真实 PDF 证据

中国太保 2023 canonical PDF SHA256：
`716a65f266f6ed6dc12f6906db26b84aeac4745c212c8cb8687c7a4fa0fc9dab`。

- 物理页 144，旧准则长标签行：`source_row_id=V2_P144_L10`，附注 2，当前期为合法破折号，
  比较期值为 26,560 / 12,353，身份为 `legacy_fvtpl_assets`。
- 同页当前交易性金融资产行：`source_row_id=V2_P144_L19`，附注 10，当前期值 581,602，
  身份为 `fvtpl_assets`。
- 两行来源 ID 不同，`required_current_member_status_valid=true`，金额几何门禁通过。

## 永久回归与验证

- 同页新旧 FVTPL 物理行、附注和金额配对回归。
- 同期间新旧来源禁止求和、认证拆分门禁、同名不同分类轴不冲突回归。
- 正式 Merge 写盘、manifest 及两份 XLSX 三工作表回归。
- v6.14 全量非浏览器 576/576；真实 PDF Shadow 15/15；金融投资七阶段验收 12/12；
  国寿真实跨准则 FVTPL Merge 53/53 桥接值、身份冲突 0。
