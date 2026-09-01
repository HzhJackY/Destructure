# CHANGE — Stage B 终态计划显式重新抓取

日期：2026-08-17

状态：`TARGETED_TESTS_PASSED / UI_MANUAL_RESTART_PENDING`

## 变更

- Stage B restore 返回持久化计划的提交完成度。
- 执行中的计划不再显示可点击但无效的提交操作。
- 终态计划可通过显式 replay 创建新 Stage B session、Research Batch 和 source batches。
- 历史会话、批次和 Capture lineage 保留不变。
- 提交成功信息在 rerun 后继续可见。

## 验证边界

- Stage B 统一面板与持久化服务定向测试通过。
- 新回归证明：普通重复提交幂等；执行中 replay 被拒绝；终态 replay 创建新 lineage；旧会话不变。
- 未运行浏览器 E2E、OCR 或新的真实 PDF Capture。
- 需用户重启 Streamlit 后进行 UI 人工点击验收。
