# INC-023 — Research Definition 提前 OCR 与跨模式页缓存不复用

## 现象

- 即使原生文本已经足以定位主表，Research Definition Stage A 仍会先为整本 PDF
  建立 `auto/400-DPI` Fast Index；年报中的无关低文本页因此提前 OCR。
- 目标资格不足时，条件 OCR 使用 `selected + force_ocr_pages` 的另一完整索引身份，
  已识别页面可能被再次 OCR。
- 中国太保 2025 同时存在第 5 页信息披露摘要表和第 74 页已审主表。简单关闭首轮
  OCR 会让摘要页提前胜出，说明修复不能只把 `auto` 改成 `off`。
- 用户侧表现为“发现主报表”等待过久，且审计无法区分完整索引命中与页级复用。

## 影响范围

- 影响 Research Definition 的主表类发现冷启动，以及候选集合变化后的条件 OCR。
- 主要影响耗时、CPU、缓存占用、主表 Anchor 仲裁和审计可解释性。
- 不据此认定既有 Capture、Canonical、Merge、Golden 或金额值错误。

## 根因

- `GenericDiscoveryService._statement_strategy` 在原生 family resolution 前无条件调用
  默认 `auto/400-DPI` Fast Index。
- 完整 Fast Index 键包含 `ocr_mode` 与整个 `force_ocr_pages` 集合；生产
  `build_fast_index` 未接入已有的页级缓存辅助函数。
- 条件 OCR 只把 OCR 文本返回给 generic discovery，丢失 `ocr_rows/ocr_words`，
  无法等价复用太保空间解析器。
- 原生 resolution 只要非空就提前结束，未检查已审财务报表目录是否指向另一个
  尚未解析的扫描主表页。
- 页缓存整份 JSON 无锁读写，并发候选集合可能相互覆盖；OCR 异常后的原生文本还
  可能被错误计为 OCR 输出。

## 修复

- 首轮 Fast Index 显式使用 `ocr_mode=off`，并把同一原生 index 传给 generic
  discovery，避免第二次建立 `auto` 索引。
- 使用已审财务报表目录作为强候选证据；目录引用页未解析时，即使早期摘要已形成
  resolution，也继续执行候选页 OCR，并在 OCR-aware index 上重新运行正式 resolver。
- 强目录命中时只 OCR 引用页和直接邻页；扫描目录采用同一 Fast Index 的两阶段、
  总页数受限兜底，不另建 OCR/Discovery/Capture 管线。
- Fast Index 页缓存保存 text、rows、words；身份与调用模式及候选集合解耦，使用
  排他锁、锁内重读合并与原子替换保证并发一致性。
- OCR 失败页不进入 OCR 输出，并持久化页级错误、命中、未命中和实际证据状态。
- 完整索引键补入 `min_native_chars`；resolution 的生产版本引用 `APP_VERSION`。

## 缓存与兼容边界

- 新完整索引 schema 为 `v6.12-fast-index-v4`，旧完整索引按 schema 失效并可重建。
- 新页缓存 schema 为 `v6.12-ocr-page-cache-v1`；身份包含 PDF SHA、pipeline、语言、
  effective DPI、渲染、红章预处理、PSM 与 fallback 合同。
- `force_rebuild=True` 明确绕过当前页的缓存读取并刷新该页；普通生产发现不使用该
  参数。缓存仅保存 OCR 结构证据，`usable_as_amount=false`。
- 不修改 PDF、用户 DATA_HOME、Capture、Canonical、Merge 或 Golden。

## 验证

- 合成/契约测试：`39 passed, 6 deselected`；6 个 deselected 均已在未改动 v6.11
  原样复现。通过项覆盖原生零 OCR、已审目录优先、扫描目录
  二阶段、OCR geometry 贯通、失败审计、顺序及并发重叠集合复用、force rebuild。
- 中国人寿 2025：SHA 匹配，Anchor 89，coverage 1.0，首轮/条件/热运行 OCR 调用均为 0；
  OCR 金额注入计数 0，冷/热耗时 `1.170s / 0.449s`。
- 中国太保 2025：SHA 匹配，首轮原生 OCR 页数 0；条件 OCR 仅第 73/74/75 页，
  Anchor 74，coverage 1.0，OCR 金额注入计数 0；冷/热耗时 `9.393s / 0.539s`，
  热运行新增 OCR 调用 0，
  更换完整索引键后 3 页全部命中共享页缓存、OCR 引擎调用 0。
- 未运行浏览器 E2E、12 份年报全矩阵、Fresh Golden/Canonical/Merge 重物化；因此本
  incident 仅判定本缺陷修复证据闭合，不宣称 v6.12 整体发行认证完成。
