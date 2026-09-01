# INC-025：Stage A Golden 成员契约跨 Registry 泄漏

## 现象

在研究引导 UI 选择 `investment_portfolio` 后，Stage A 却显示
`fvtpl_assets`、`debt_investment`、`other_debt_investment`、`other_equity_investment`
缺失，阻止投资组合 Anchor 认证。

## 根因

`_render_golden_anchor_check()` 仅以公司、年份和候选 child rows 调用 Golden 比较器，
没有传递 Registry Family。已有 Golden Anchor 事实仅覆盖金融投资成员，导致同公司同年度的
投资组合候选错误继承金融投资必需成员集合。

## 修复

Golden Anchor 门禁改为显式依据候选/Definition/知识包确定 Family，且仅
`financial_investment` 调用现有金融投资 Golden comparator。其他 Family 显示无已注册
Anchor Golden 契约，并继续使用当前 Registry 的机器证据和原 PDF 审核。

## 回归

- 投资组合不调用金融投资 Golden comparator；
- 金融投资保留原有 Golden comparator 调用；
- 不修改 Golden 数据、不创建自动认证绕行。

## 闭环状态

状态：`RESOLVED_IN_V6.13`

- `investment_portfolio` 已接入自己的 Stage A 拓扑与 Golden 比较器。
- 平安 2023 真实离线基线得分 1.00，未出现任何金融投资成员缺失提示。
- 10 份上市母公司年报的 Stage A 核对为 10/10 MATCH。
- 按用户要求未运行浏览器 E2E；UI 结论来自定向组件测试和同一后端离线执行。
