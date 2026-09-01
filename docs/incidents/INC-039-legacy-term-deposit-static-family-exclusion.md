# INC-039：旧准则定期存款被静态族外规则误排除

## 现象

`FINANCIAL_INVESTMENT_V1` 对中国人寿 2023 合并资产负债表执行正式 Discovery 时，PDF 与 Golden 均明确包含“定期存款”及金额 404,131，但 Statement Family Resolution 将 `time_deposits` 标记为 `OUTSIDE_FAMILY`，导致 Golden Anchor 比较报告缺少 `term_deposits`。

## 根因

`expected_member_resolver.py` 保留了 v6.11 时代的静态全局排除集合，把 `time_deposits` 与 `long_term_equity` 一并视为族外成员；v6.13 的版本化 Registry 合同已经把 `time_deposits` 注册为旧准则披露的 direct member。静态规则覆盖了正式 Registry 合同，形成双重且冲突的口径所有权。

## 修复

- 从静态全局族外集合中移除 `time_deposits`；`long_term_equity` 继续保持族外。
- 旧准则隐式成员集合可包含 `time_deposits`。
- 新准则显式“金融投资”父块仍依赖物理父块边界，不吸收父块外的定期存款。

## 验收边界

- 定向单元测试同时覆盖旧准则隐式成员集合与新准则显式父块。
- 中国人寿 2023 使用当前生产 PDF 重跑 Discovery、Golden 比较和正式认证。
- 不修改 Golden 金额，不直接写认证表，不执行浏览器 E2E。
