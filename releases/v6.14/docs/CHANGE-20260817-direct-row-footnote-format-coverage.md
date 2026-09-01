# CHANGE — Direct 行尾脚注格式覆盖补全

日期：2026-08-17

状态：`IMPLEMENTED / TARGETED_AND_REAL_PDF_CANARY_PASSED / NO_BROWSER_E2E`

## 变更

- 既有名称正规化函数新增裸数字和“注+数字”候选格式。
- Direct PDF 证据认证复用共享候选正则，没有新增格式专用函数或平行正规化路径。
- 所有格式继续要求上标几何或同页编号注释证据；无证据候选 fail-closed 保留原名。
- 新增国寿裸上标、太保“注+上标”以及无证据保留的回归断言。

## 验证边界

- 受影响脚注、名称身份与 Direct 复合表回归：28 passed / 1 deselected。
- Python 静态编译：通过。
- 真实 PDF 页面级 Canary：国寿 2025 裸上标与太保 2025“注+上标”2/2 通过；
  两者均产生 `NATIVE_SUPERSCRIPT_GEOMETRY` 证据并正确保留 raw/剥离 normalized 后缀。
- 同测试文件的完整运行另有 1 个既有单位可换算冲突断言失败；该测试不经过名称正则或
  脚注证据路径，本次未修改单位合同。
- 不运行浏览器 E2E。
- 未运行生产 Fresh Capture → Canonical → Merge → XLSX 全链。
- 历史 Capture 不改写；Streamlit 重启并重新抓取后才产生新正规化身份。

