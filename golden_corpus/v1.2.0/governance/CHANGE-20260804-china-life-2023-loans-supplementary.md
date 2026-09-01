# Change Report — 中国人寿 2023 贷款补充表身份迁移

Date: 2026-08-04
Change Log ID: `ACL-1.1.6-CHINA-LIFE-2023-LOANS-SUPPLEMENTARY`

## Changed

- reader p174 `8. 贷款` 的 6 行、12 个值保留在 primary Golden。
- reader p175 `(b) 其他贷款` 到期期限分析的 6 行、12 个值从 primary Golden 迁入独立
  `SUPPLEMENTARY_TABLE` Golden。
- 新增 `CHINA_LIFE_2023_SUPPLEMENTARY_LOANS_OTHER_MATURITY` logical/physical segment；
  未创建 `CONTINUATION_SEGMENT`。
- Golden validator 优先消费 schedule 显式 `member_id`，旧 schedule 保持兼容。
- 通用修复报告文件名连接字残留，`中国人寿2023年年度报告.pdf` 投影为 `中国人寿`。
- 保留原始 `raw_item`，在 normalized identity 通用清除行尾脚注引用；按缩进同级子行、
  subtotal/total 闭合和嵌套单子项结构恢复父级，未按公司/年份硬编码。

## Evidence

- canonical PDF SHA256 与 filing Golden 完全一致。
- PDF reader p174/p175 文本层逐行核验标题、期间、分类轴、行序和金额。
- 两页 180 DPI 原图逐页视觉核验；p175 六行后出现 peer note `9. 定期存款`。
- 金额未从 Capture/parser 输出反推；既有金额仅在 Golden 表身份之间迁移。

## Contract

- Golden 只作独立验收/认证证据，不反向生成 runtime manifest。
- supplementary 自动认证必须来自 candidate inventory 的 bbox/period/header/amount-lane
  完整 signature coverage、有界原生文字来源与明确 reset relation；否则保持未决。

## Release State

- `PRIMARY_ONLY` 继续 `CLEAR`，其期望范围只包含 p174 主余额表。
- `ALL_NOTE_TABLES` 继续 `BLOCKED_PENDING_CERTIFIED_CONTINUATION_AUDIT`；新增已认证补充表
  不等价于同附注全部边界审计完成。

## Validation

- Golden registry validator：`VALID`，53 primary、14 supplementary、0 certified true
  continuation segments。
- 解析与跨公司定向回归：`49 passed`。
- 中国人寿 2023 fresh `PRIMARY_ONLY`：5/5 jobs `SUCCESS`、review 0、merge-ready 5/5，
  company display=`中国人寿`，正式数据库未修改。
- 更新后 primary Golden：82 expected / 82 PASS / 0 FAIL / 0 label mismatch / 0 missing。
- 持有至到期投资有 10 个 2022 Capture 单元未被当前 Golden 断言覆盖，保留非阻断 warning。

## Rollback

恢复 primary/supplementary YAML、segment/coverage registry、change log 和公司名规范化函数；
保留本报告与 PDF 证据供审计。
