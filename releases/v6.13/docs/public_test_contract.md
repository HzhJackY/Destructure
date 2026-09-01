# 公开测试合同

本候选只分发可由合成输入、临时目录、临时 SQLite、mock OCR 或静态源码契约
独立执行的测试。以下内容不进入公开 `tests/`：

- 真实年报、真实页码或真实金额验收；
- Golden corpus 与生产 `DATA_HOME`；
- 公司专用解析验收和内部重验证运行器；
- 依赖相邻历史发行目录的旧回归脚本；
- Playwright、浏览器或本地 Streamlit 用户旅程；
- `__pycache__`、`.pyc` 等运行时产物。

本轮从 staging 的 103 个测试文件/产物中保留 51 个、隔离 52 个。精确清单和
SHA-256 由发行工程证据中的 `public_test_distribution_inventory.csv` 管理。

初次收集还发现 `test_v611_certified_document_index_profile.py` 依赖未公开的内部
`run_12_filing_matrix` 运行器；它作为传递边界漏项被隔离，没有通过补回内部运行器
来扩大公开范围。

## 当前验证状态

在全新 Windows / CPython 3.14.5 环境中，保留的完整公开安全集合结果为：

- 346 tests；
- 346 passed；
- 0 failed；
- 未运行浏览器 E2E、真实 PDF、Golden、Discovery 或真实 OCR。

2026-08-11 的 v6.12.1 公开候选已修复此前 8 个失败节点，并运行完整保留集合：

- 346 tests；
- 346 passed；
- 0 failed。

修复包含金融投资 family 外成员、discovered-row resolution 返回、原生文本 OCR 审计状态、
审核队列路由和公开可再分发的合成多分块不变量探针。完整说明见
`docs/INC-20260811-public-contract-repair.md`。这不替代浏览器 E2E、真实 PDF、Golden、
Discovery/OCR 或生产 DATA_HOME 验收；它们仍按本候选边界未运行。

## 执行命令

```powershell
uv sync --frozen --extra dev --no-install-project
uv run pytest -q
python examples/synthetic/run_smoke.py
```

锁文件存在、安装成功和合成 Smoke 成功分别属于不同证据层，任何一项都不能替代
当前已通过的公开安全测试门；它仍不替代未运行的验收门。
