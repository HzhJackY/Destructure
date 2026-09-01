# INC-035 — Direct 投资组合名称脚注与多计量单位身份错误

状态：`RESOLVED_REAL_PDF_VERIFIED_NO_BROWSER_E2E`

## 现象

新华保险 Direct 投资组合研究宽表把行尾数字脚注带入“项目”名称，跨年度相同项目因脚注号
差异被拆成不同身份。部分 Capture 又以整表单单位解释金额和占比，Merge 输出 `%` 或
`REVIEW_REQUIRED[%|百万元]`，金额列还可能缺少有效单位。

## 根因

- Capture 只有字符串清洗结果，没有把脚注候选、认证证据和原文身份分层持久化。
- Direct 前缀拆分、父组拆分和续行拼接存在各自的名称处理入口。
- Stage A 认证金额单位在物理 Capture 完成后才回填 `result.unit`，构造 `TableCell` 时无法消费。
- Merge 在行级跨 measure 聚合单位，把金额和占比的合法单位差异误判为冲突。
- 研究宽表固定“单位”列隐含“一行只有一个单位”，与多 measure observation 合同冲突。

## 修复

- `raw_item` 保持原文，`normalized_item` 作为 Canonical/Merge 名称身份；所有 Direct 标签派生
  统一调用结构化正规化器。
- 尾随数字脚注只有原生上标几何或同页编号注释证据成立时剥离；marker、page、bbox/span、
  method 写入 Capture Long。无证据候选 fail-closed 为 `ROW_LABEL_FOOTNOTE_UNRESOLVED`。
- 认证金额单位在物理 Capture 前注入；金额 cell 使用认证金额单位，占比/增减率使用 `%`，
  `value_yuan` 只对金额计算。
- Merge 单位冲突按同一 observation identity、同一 measure 检查；缺单位金额 observation
  以 `UNIT_UNRESOLVED_AMOUNT_OBSERVATION` 阻止进入 Merge。
- 研究宽表删除固定“单位”列，导出合同升级为 v3，单位由各数值列的
  `currency_unit + measure` 表头表达。
- Golden 行级验收使用逻辑原文 `row_item_raw`，旧 Capture 才回退物理原文
  `raw_item`；轴标题或父组前缀继续保留在 provenance，不再造成假阳性失败。
- 研究宽表“项目”列加宽，避免长会计计量名称在可下载工作簿中截断。

## 验证边界

- 名称、脚注证据、Capture Long、多计量单位、Merge 和研究宽表定向测试 45/45 通过。
- 新华 2023–2025 在全新隔离 DATA_HOME 中 3/3 通过：每年 1 个物理作业、3 个逻辑
  Capture，Capture 行级 Golden 均为 `MATCH`，OCR 均为 0。
- 三年共 244 个非空数值 observation；金额单位错误、比例单位错误、非金额
  `value_yuan`、`REVIEW_REQUIRED` 单位冲突均为 0。三份研究宽表结构、公式错误扫描和
  渲染检查通过。
- 扩大相关回归为 134 passed / 1 failed。唯一失败是既有拓扑 Resolver 用例
  `test_separate_same_page_tables_keep_two_physical_identities` 缺少
  `selected_topology`，不经过本事故修改的名称、单位、Merge 或导出路径。
- 未迁移历史 Capture，未写生产 DATA_HOME，未运行浏览器 E2E。
