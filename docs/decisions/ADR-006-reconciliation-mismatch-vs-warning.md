# ADR-006 — 勾稽语义拆分：MISMATCH（阻塞）与 WARNING（非阻塞）

Status: ACCEPTED

## 背景

`RECONCILIATION_WARNING` 名称含 “warning”，却被 reducer 放入 `blocking_issues`
并阻止合表，命名与行为矛盾。勾稽审计同时存在两类不同语义：

- **已证实的数值不一致**（合计/小计与明细之和超出容差）——需要人工复核，应阻塞；
- **无法证明/不确定**（无合计、无对应数值、公式推断不确定）——不构成错误证据，不应阻塞。

## 决策

1. 块级 `_reconciliation` 状态改为 `PASS` / `MISMATCH` / `NOT_TESTABLE`；
   任一检查失败即 `MISMATCH`（不再叫 `WARNING`）。
2. reducer / capture_readiness 对状态
   `WARNING`（旧 artifact 兼容）/ `MISMATCH` / `FAIL` 产生阻塞码
   `RECONCILIATION_MISMATCH`（merge blocker `V69_RECONCILIATION_MISMATCH`）。
3. `RECONCILIATION_WARNING` 保留在评审目录，但为非阻塞（LOW）语义，
   不再由 reducer 产生进入 `blocking_issues`。
4. `NOT_TESTABLE` / `PASS` 不产生勾稽阻塞。

## 影响

- 安全门未放宽：真实的合计/明细不一致仍阻塞合表，仅阻塞码更名。
- 旧 artifact 中状态 `WARNING` 仍按 MISMATCH 阻塞，保证历史数据不回退。
- UI 评审目录与路由新增 `RECONCILIATION_MISMATCH`。

## 依据规则

- Rule 002/003：未验证的数值不得进入合表通道。
- Rule 013：阻塞语义变更，以 ADR 记录。
