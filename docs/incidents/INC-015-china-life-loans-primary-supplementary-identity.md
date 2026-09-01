# INC-015 — 中国人寿 2023 贷款主表混入独立到期期限表

## 现象

- `PRIMARY_ONLY` Golden parity 将 PDF reader p175 的 6 行、2 期间贷款到期期限金额报为
  `CELL_NOT_FOUND`。
- p174 已成功抓取余额表，但旧 Golden 把 p175 的另一维度分析也列在同一个
  `PRIMARY_TABLE` 断言中。
- Capture 展示字段为 `中国人寿年`，权威 `company_id=中国人寿` 未受影响。

## 根因

- Golden 迁移历史仅依据相同附注号和“续”标题，把 p175 到期期限分类轴误当作 p174
  主余额表的剩余行，没有执行逻辑表维度重置判定。
- `batch_pipeline.infer_company_year()` 先删除 `2023`，再删除 `年度报告`，使文件名
  `中国人寿2023年年度报告.pdf` 残留连接字“年”。
- 同一批 parity 的行身份差异还暴露出通用父分组保留与脚注尾标清洗缺口；该代码根因由
  共享 hierarchy 修复处理，不以修改 Golden 标签掩盖。

## PDF 独立证据

- canonical PDF SHA256：`5ea1048c3a9323b37b1ad2e870da0fb54d9cfacdfba159aad4b9bec070edc18a`。
- reader p174 的 `8. 贷款` 包含六行余额/净值/公允价值并自然结束。
- reader p175 在 `(b) 其他贷款` 下重新声明“到期期限”和 2023/2022 两列，六行后进入
  下一附注 `9. 定期存款`；它是独立补充表，不是真正 continuation。
- 文本层与 180 DPI 页面渲染逐项核验一致，未从 Capture 输出反推金额。

## 修复

- 将 6 行 × 2 期间从 primary Golden 迁入独立 `SUPPLEMENTARY_TABLE` Golden，并登记
  稳定 logical/physical segment 身份；`PRIMARY_ONLY` 仍只选择 p174。
- Golden coverage 的 primary assertions 94→82，supplementary 表 2→3、assertions
  54→66；期间总断言不变，`ALL_NOTE_TABLES` 继续保留 continuation audit 阻断。
- 通用修复报告文件名中可选连接字“年”，不按公司分支、不修改 `company_id`。
- `raw_item` 保留原 PDF 文字；`normalized_item` 通用剥离行尾 `(a)/(b)`、完整
  “（附注…）”引用和受限尾标“注”，并用负例保护“备注/附注/标注”等词义。
- 对“文本父组 → 至少两条同缩进金额子行 → 小计/合计回到父缩进”的结构建立父级；
  小计闭合父组。对“小计 → 新文本外层 → 单个缩进子项 → 总计”的嵌套结构，保留
  外层父级并防止 grand total 继承上一分类轴。规则只消费版面和行序，不按公司分支。
- Golden 不反向写 runtime manifest；candidate 的 bbox/period/header/lane 覆盖或 reset
  relation 不完整时仍 fail-closed。

## 永久回归

- 文件名身份投影覆盖带/不带 SHA 前缀及 `年年度报告`、`年报`、`年度报告` 变体。
- Golden validator 必须验证显式 supplementary `member_id=loans`、页面、12 个金额和
  coverage/segment registry 一致。
- 国寿 2023 fresh `PRIMARY_ONLY` 必须通过 Golden parity 且不包含 p175 到期期限表；
  supplementary 验收单独执行。

## 验证结果

- 通用定向/跨公司回归：`49 passed`。
- 国寿 2023 fresh `PRIMARY_ONLY`：`5/5 SUCCESS`、`review=0`、`merge_ready=5/5`，
  manifest/inventory 全部 `VALID`，展示公司名为 `中国人寿`。
- primary Golden：`82/82 PASS`，`LABEL_IDENTITY_MISMATCH=0`、`CELL_NOT_FOUND=0`；
  持有至到期投资另有 10 个 2022 Capture 单元尚无 Golden 断言，仅作 warning。
- 正式 metadata.db SHA256 前后均为
  `4760f96be4a5059c0f8ecfa4f9da31bbada1a58fc193816f18f0a25188917346`。

## 2026-08-05 Streamlit Golden 成员别名漏判

- 现象：Stage-A 界面将已发现的 `legacy_loans` / `603,639` / `附注十-8`
  误报为“未找到”，并由 Golden 门禁阻止 Anchor 认证。
- 根因：机器行在 lookup 前通过显式别名规范为 `loans`，而 Golden
  原始 `member_id=legacy_loans` 未经同一规范化便查找 `actual`，形成单侧别名漏判。
- 修复：Golden 当前期成员查找使用与机器行相同的 `_member_id()`
  lookup identity；返回行仍保留原始 `member_id=legacy_loans` 供审计。
- 回归：中国人寿 2023 五个当前期成员全部 `MATCH`；正式库最新
  occurrence 只读 canary 为 `MATCH`、`missing_current_members=[]`，数据库哈希在本次
  只读检查前后一致。
