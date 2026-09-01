# ADR-007 — 父子行勾稽不一致为非阻断警告

Status: ACCEPTED

## 背景

ADR-006 将算术检查失败标记为 `MISMATCH` 并纳入合表阻断。现有检查以“合计行前
所有数值行的平铺求和”验证总额，不能可靠识别所有年报中的父子层级、多块表或
非加总披露。因此，父行合计与子行和不吻合是重要审计信号，但不是足以拒绝整表
合并的通用证据。

## 决策

1. `_reconciliation` 继续写入 `MISMATCH` 及逐列差额证据，不改写机器事实。
2. `MISMATCH` 和兼容旧 artifact 的 `WARNING` 均由 CaptureDecisionReducer 生成
   非阻断 `RECONCILIATION_WARNING`，不进入 `blocking_issues`。
3. `capture_readiness` 不再将 `MISMATCH` / `WARNING` 写入 merge blockers；只有
   `FAIL` 仍维持阻断，防止技术性校验失败被静默放行。
4. 算术 PASS 仍可作为页末边界推断的正向证据；本决策不放宽该边界安全条件。

## 影响

- ADR-006 中“真实不一致仍阻断合表”的决策被本 ADR 取代。
- 中国太保等已知父子行结构的勾稽差异作为可审计遗留警告保留，不阻断合表。
- 不实现跨年报通用的父子行识别或金额修正。

## 依据规则

- Rule 002/003：不创造或修正金额，保留来源与差额证据。
- Rule 013：合表阻断语义变化以 ADR 留痕。
