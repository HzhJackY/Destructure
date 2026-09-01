# INC-20260818：旧 Capture 合表父 ID dtype 冲突

## 现象

合表加载旧 `table_raw_long.csv` 时，`project_certified_row_hierarchy()` 在补入
兼容父 ID 的赋值阶段抛出：

```text
TypeError: Invalid value '<ArrowStringArray> ...' for dtype 'float64'
```

## 根因

旧 Capture 的 `parent_row_id` 全为空。pandas 对 CSV 空列推断为 `float64`，而身份
投影需要向同一列写入字符串父行 ID。新版本的严格 dtype 规则拒绝隐式 upcast。

## 修复与边界

投影入口将 `source_row_id`、`parent_row_id` 统一转换为可写的 `object` 容器，再执行
既有认证/兼容投影。未改变父子裁判、Capture 身份、Canonical/Merge 键或生产数据。

## 验证

`tests/test_v613_merge_parent_id_dtype.py` 覆盖 `read_csv` 的 `float64` 空列和 Arrow
`string` 列；父子层级与身份迁移定向测试全部通过。浏览器 E2E、生产 DATA_HOME 和真实
PDF 未在本轮修改。
