# INC-20260817 — Stage B 终态会话重新提交无可见响应

## 现象

UI 已展示 Capture Plan，点击“确认逻辑表并抓取”后未创建新作业，界面也没有留下可见反馈。

## 根因

Stage B session identity 仅由 plan IDs 和 capture scope 确定。对已完成的相同 plan/scope，
`create_execution_batch` 按幂等合同返回历史批次。面板却始终显示首次提交按钮，且
在 `st.success()` 后立即 `st.rerun()`，导致返回旧批次的反馈瞬时消失。

生产 DATA_HOME 只读核对显示，当前三份太保 Capture Plan 命中 2026-08-16 的同一会话，
其 3 个 source batch 均已 `SUCCESS`；用户本次点击未产生新会话或 job。

## 修复

- 恢复状态显式输出 `all_plans_submitted` 和 `submitted_plan_ids`。
- 已提交且未终态时禁用重复提交，显示正在执行。
- 终态时改为明确的“重新抓取当前逻辑表”，创建新 execution attempt 及新 lineage。
- 提交反馈先存入 Streamlit session state，在 rerun 后显示。

## 不变项

不修改 CertifiedChildTableLink、ROI、PDF/OCR、Capture 解析、Golden 或历史 Capture；
普通首次提交和重复 API 调用仍保持幂等。
