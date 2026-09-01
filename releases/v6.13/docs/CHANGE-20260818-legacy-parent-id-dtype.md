# Change Report：旧 Capture 父 ID dtype 修复

## 变更

在 `financial_structure_resolver.project_certified_row_hierarchy()` 入口，将两列行身份
转换为可写 `object` dtype，避免空历史列的 `float64`/Arrow 字符串 dtype 阻止字符串父 ID
投影。

## 影响

仅影响 UI/Merge 的只读身份投影兼容层；不重新推断父子关系，不修改原始 Capture、Golden、
生产 DATA_HOME、金额、ROI 或物理作业身份。

## 验证范围

- py_compile：通过
- 定向身份、父子层级、迁移回归：通过
- 浏览器 E2E：按用户要求跳过
- 真实 PDF/生产合表：未运行

## 回退

移除入口 dtype 归一化即可回退；无数据库迁移。
