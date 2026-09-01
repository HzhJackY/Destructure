# INC-20260811：公开候选的契约回归与发行门禁修复

## 现象

v6.12 公开候选的公开安全测试为 344 项，其中 8 项失败；候选同时缺少项目许可证。失败混合了业务契约缺口、UI 路由可达性、审计状态覆盖，以及公开包错误依赖已隔离的内部测试文件。

## 根因

1. `time_deposits` 未被列为金融投资 family 外成员。
2. `resolve_discovered_rows` 漏加入 `page_resolutions`。
3. 原生文本发现成功后，未触发的条件 OCR 分支可覆盖最终审计状态。
4. 研究任务审核页没有复用逻辑资产工作区的 `REVIEW_REQUIRED` 队列入口，且综合认证评分未展示。
5. BUG-010 至 BUG-012 的不变量注册表动态依赖一个含内部/真实数据表面的测试文件，违反公开包边界。

## 修复

- 将 `time_deposits` 加入 `FINANCIAL_INVESTMENT_OUTSIDE_MEMBERS`。
- 在 discovered-row compatibility 路径保留 resolution 输出。
- 保留原生文本成功的最终审计状态；不让 OCR 策略未触发伪装为主表发现失败。
- 为研究任务审核增加只在用户点击时写入 session state 的 `REVIEW_REQUIRED` 工作区队列入口，并展示 `certification_score`。
- 新增仅含合成数据的 `public_multiblock_invariant_probes.py`，替代被隔离测试中的三项不变量来源。
- 项目许可证确定为 `AGPL-3.0-only`；此 incident 当时保留的第三方义务门禁，已由
  2026-08-12 Windows runtime provenance 与三资产联合发行闭包关闭。

## 验证与边界

- 定向回归：33 passed。
- 公开安全测试全集：344 passed。
- 未运行浏览器 E2E、真实 PDF、Golden、Discovery/OCR 或生产 DATA_HOME；不得据此标记 `RELEASE_CERTIFIED`。
