# INC-025 — 投资组合 Stage A 误用金融投资成员门禁

状态：RESOLVED

## 现象

选择投资组合 Registry 后，Stage A 错误提示 `fvtpl_assets`、`debt_investment`、
`other_debt_investment`、`other_equity_investment` 缺失。

## 根因

Golden Anchor UI 没有以 Registry Family 为调用边界，同公司同年度的金融投资 Golden
成员集合泄漏到投资组合候选。

## 修复与验证

- Golden 门禁按 Family 路由；投资组合使用专属拓扑/Golden comparator。
- 投资组合 Stage B 使用直接物理表认证，不调用金融附注检索。
- 10 份上市母公司年报 Stage A 10/10 MATCH；平安 2023 全离线链路通过。
- 金融投资原 comparator 和审核合同保留。
- 按用户要求未运行浏览器 E2E。
