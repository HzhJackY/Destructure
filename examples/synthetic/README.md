# 纯合成空 DATA_HOME smoke

该示例只验证公开源码候选能在一个全新的临时 `DATA_HOME` 中完成目录初始化、SQLite registry schema 初始化及空状态统计。

## 数据与执行边界

- 不包含、读取或下载真实 PDF、Golden、用户数据或缓存。
- 不创建公司、金额、保单或其他业务记录；registry 业务表预期全部为零行。
- 不调用 Streamlit、浏览器 E2E、OCR、Discovery、LLM 或网络服务。
- 临时目录由 Python `tempfile` 创建，并在脚本退出时清理。
- 输出不包含随机临时路径或时间戳，可与 `expected_summary.json` 做精确比较。

## 运行

在公开候选仓库根目录执行：

```powershell
python examples/synthetic/run_smoke.py
```

预期进程退出码为 `0`，JSON 中 `status` 为 `PASS`、`business_records_created` 为 `0`，且 `registry_table_counts` 中的所有计数均为零。

运行非 E2E 回归：

```powershell
python -m pytest -q tests/test_public_synthetic_smoke.py
```

`expected_summary.json` 是确定性输出合同；当 registry 或 DATA_HOME schema 正式升级时，应在同一变更中审阅并更新该文件。

