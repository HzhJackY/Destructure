# INC-038：Golden 逐行位置比较掩盖行身份与父子差异

- 状态：FIXED_IN_ACCEPTANCE_HARNESS
- 日期：2026-08-23

## 问题

投资组合 Capture 验收历史上按列表位置连接 Golden 与机器行。表头误入、缺行、同名行、
分类轴拆分或父子边漂移时，后续所有行会整体错位，无法区分“值错”与“身份错”。金融投资
子表身份也散落在 filing/page anchor/Golden 文件中，严格验收没有统一入口。

## 修复

- 增加 Golden Identity v1.2 sidecar 与严格 schema；
- 投资组合按稳定复合业务身份连接，不再按列表位置连接；
- 连接后独立检查 runtime `source_row_id`、父子图、期间、measure、unit 与数值；
- 金融投资 Capture 复用既有 certified child comparator，并从正式 Capture Request 取得
  member table 身份；
- 缺身份、重复身份、悬空父项、错误 PDF 哈希与跨 Registry sidecar 均 fail-closed。

## 当前影响

2026-08-23 live 只读快照因此暴露投资组合历史 Capture 的父子/行身份差异；这些不是由
Golden 自动修正的值。必须在隔离 DATA_HOME 通过最新正式 Capture 重跑后再判定是否已修复。

