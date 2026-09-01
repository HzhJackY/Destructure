# INC-024 — 合表标签回退缺失与排序控件无条件显示

- 状态：RESOLVED
- 修复版本：`releases/v6.12`
- 日期：2026-08-10
- 冻结回退基线：`releases/v6.11`（未修改）

## 现象

1. 合表来源或项目缺少 `display_name` 时，下拉标签直接显示 `None · <run_id>`。
2. 国寿 2025“其他权益工具投资”的 b2/b3 内部 Capture 目录采用 ASCII 安全后缀，UI 在名称回退失败时暴露连续下划线，遮蔽原本已保存在 metadata 中的“按计量构成”和“按上市状态”。
3. 创建合表时，“排序基准表”下拉在排序策略之前且始终显示；选择“按年份附注号排序”后仍展示无关控件。

## 影响

缺陷只影响合表 UI 的标签与控件编排，不修改 Capture、Logical Asset、Canonical、Merge manifest 或研究宽表。主表、b2、b3 的三个 Capture ID 与 classification axis 始终独立，没有发生资产合并或数据污染。

## 根因

- `app.py` 多个下拉直接格式化可空 `display_name`，绕过已有的安全标签函数。
- 中文块标题仍存在于 `classification_axis`、`table_query`、`source_table_title` 和 block metadata；但 UI 没有按这些字段回退，因而把仅用于路径安全的 ASCII 后缀当成了可读名称。
- 排序基准 Capture 下拉在策略 radio 之前无条件渲染，导致控件可见性与有效策略不一致。

## 修复

- `merge_asset_picker_ui.py` 统一 Capture 与合表项目标签：优先使用可读业务维度/标题，缺失名称时回退稳定 ID，标签始终保留 Capture ID 防止重名碰撞。
- ASSET_TYPE、MEASUREMENT_COMPOSITION、LISTING_STATUS 显示为“按资产类型”“按计量构成”“按上市状态”；无 axis 的生产投影继续从中文 `table_query`/`source_table_title` 回退。
- 新增只读 UI 组件 `merge_order_controls_ui.py`：先选择策略；默认策略只显示基准 Capture；年份策略只显示基准年份；隐藏的基准 Capture 使用首个有效来源作为稳定回退。
- 无有效年份时，界面明确提示并把有效策略降回默认基准表策略，不写入名义 NOTE 策略和空年份。
- 不重命名既有 b2/b3 目录或 Capture ID，不改排序算法与业务持久化路径。

## 验证

- 定向非 E2E pytest：`22 passed`。
- 受影响非 E2E pytest：`59 passed`。
- 隔离合成 DATA_HOME 的浏览器验证在用户后续要求跳过 E2E 之前已完成：三块标签可读、三 ID 独立、两策略条件控件正确、浏览器 console error 为 0、未创建 Merge Project；指令到达后未再运行 E2E。
- 独立静态复核：0 阻断项；其指出的“无 axis 中文标题回退”和“策略往返”两项测试缺口均已补回归。
- v6.11 冻结清单：333/333，0 missing，0 mismatch。

## 未执行边界

未运行真实 PDF Canary、Fresh Golden、Discovery/OCR、Stage B、Capture、Canonical、Merge 或研究宽表重物化。本缺陷不触及这些路径，不能据此声明 v6.12 整体发行认证完成。
