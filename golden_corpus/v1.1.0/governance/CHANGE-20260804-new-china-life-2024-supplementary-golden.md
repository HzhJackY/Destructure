# Change Report - 新华保险 2024 Supplementary Golden 补回

Date: 2026-08-04
Change Log ID: `ACL-1.1.2-NEW-CHINA-LIFE-2024-SUPPLEMENTARY-GOLDEN`

## Changed

- 新增新华保险 2024 `supplementary_golden_values.yaml`。
- 认证债权投资和其他债权投资各自 2024/2023 年 ECL 变动表，共 4 张独立
  `SUPPLEMENTARY_TABLE`、84 个金额单元。
- 更新 filing coverage 与 table/segment registry；`ALL_NOTE_TABLES` 对该 filing 改为
  `CLEAR`。
- 认证 p192–196 范围不存在 true continuation；p197 的附注 15 是 peer boundary。
- validator 的分类汇总改为从 registry 动态计算，移除旧硬编码计数。

## Evidence

- 用户提供的五页截图。
- SHA 绑定的 canonical PDF `新华保险2024年报.pdf` 直接渲染 p192–197。
- pypdf 文本层用于金额交叉核对；表格身份、边界和列拓扑以原图为准。

## Non-circularity

本次金额不来自 parser、Capture、UI 或当前软件输出；Golden 不回写任何生产数据库。

## Rollback

删除新增 supplementary YAML 和四条 segment registry 记录，并按本 change-log ID 恢复
新华 2024 coverage 行；保留证据与本 Change Report 供审计。
