# Changelog

## v6.14 — 2026-08-29（中国人保双 Registry 下游验收）

- 金融投资 Stage B 在候选页 OCR 结构恢复成功后，将 PDF-point 词级几何冻结到认证分段；
  Whole-table Capture 通过既有认证几何重放入口保留 Native 标签身份并读取 OCR 数值 lane。
- 统一 Stage B/Capture 的主表下界：只有认证数值 lane 上的表格行可扩展物理 BBox，表后含
  数字说明和 OCR 乱码不再造成 segment manifest drift。
- 中国人保金融投资 2023–2025 在全新隔离 lane 完成 Stage B 12/12、Capture/Canonical
  12/12、按四个 member 隔离的正式 Merge 8/8；投资组合既有 Stage B/Capture/Canonical/
  Merge 三年验收保持通过。受影响回归 127/127，生产 DATA_HOME 未写入；浏览器 E2E 仍为
  `SKIPPED_BY_USER`，FakeStreamlit 下游 parity 本轮未运行。

## v6.14 — 2026-08-28（中国人保双 Registry Stage A 修复）

- 金融投资 Native V2 与 OCR recovery evidence 改为 append-only 修订后再排名，消除 UI 展示瞬态 V2、认证入口却重载 V1 occurrence 的断层。
- Fast Index 兑现 `FINANCIAL_TABLE_400DPI_V1` 的 Tesseract PSM 4；缓存身份新增 PSM 与 wide-band-safe 红章预处理版本，避免清除中国人保投资组合的彩色表头带。
- 投资组合 Direct Discovery 在 Native 物理身份充分但数值层不足时，只 OCR 已定位候选页；词级 BBox 用于安全重建跨基线日期，Native 继续拥有标题、分类轴和物理资产身份。
- 中国人保三年真实 FakeStreamlit Stage A：投资组合 3/3 与金融投资 3/3 均为唯一 `RECOMMENDED/PRESELECTED`；2024 两个 Registry 均保持 Native-only，2023/2025 使用候选页恢复。未运行浏览器 E2E、Capture、Canonical 或 Merge。

## v6.13 — 2026-08-17（Stage B 终态计划显式重新抓取）

- 修复已完成的相同 Capture Plan 再次点击时只幂等返回旧批次、界面看似无响应的问题。
- 执行中的 plan 明确禁用重复提交；终态 plan 显示“重新抓取当前逻辑表”，
  并创建新 Stage B session、Research Batch 和 source batches，不覆盖历史 Capture lineage。
- 提交结果改为在 Streamlit rerun 后显示；普通首次/重复 API 提交仍保持幂等。
- Stage B 面板、持久化服务和投资组合拓扑定向回归 55/55 通过；未运行浏览器 E2E、OCR 或新的真实 PDF Capture。

## v6.13 — 2026-08-13（认证 ROI 行归属语义 P0）

- 修复已认证 ROI 在 Capture 解析与 DIRECT_PORTFOLIO 治理之间的语义分裂：两端现复用
  同一个纯函数，以 bbox 纵向中心和横向相交判断行归属，不再用完整字形 bbox 包含二次否决。
- 规则与“合计”或其他末行标签无关；Stage A 文本边界、物理底线识别和通用未认证
  Boundary Resolver 均未改变。
- 国寿 2024/2025 真实 PDF 只读内存重放分别为 26/22 行、治理 VALID；2023 的 14 行成功路径
  不回退，三份 OCR 均未使用。合成/契约 13/13、受影响回归 73/73。
- 未重试生产 Job，未写生产 DATA_HOME/Capture/Registry；浏览器 E2E、Canonical、Merge、
  Golden 验收未运行。


## v6.13 — 2026-08-13（PDF 源资产生命周期）

- 数据资产管理中心新增单个 PDF 的依赖预览、回收、恢复和永久删除；UI 只调用
  `PdfService`，不直接操作文件或 SQLite。
- PDF 回收采用 DATA_HOME 内的 `uploads/_trash` 可恢复移动。任何 Registry 中的
  Capture、Discovery、Occurrence 或认证链标量引用都会阻止回收，不级联删除机器证据。
- 永久删除只允许回收站资产，必须输入精确 `DELETE <pdf_id>`；成功后同时清除 PDF、
  `pdf_assets` 索引、SHA Fast Index/OCR cache 和 text index，并写 Registry 审计事件。
- Registry schema 升至 17；全量同步保留 TRASHED PDF，陈旧 upsert 不能将其意外恢复。
- 隔离 DATA_HOME 生命周期测试 8/8、受影响回归 53/53 通过；按用户既定边界未运行浏览器 E2E，
  未对真实 PDF 执行删除 Canary。

## v6.13 — 2026-08-13（Guided Discovery 重放幂等与逐 PDF 失败可见性）

- 修复投资组合 Guided UI 第二次发现时，确定性 `discovery_id` 被再次 `INSERT` 而触发
  `machine_discoveries.discovery_id` 唯一约束的问题；相同机器证据现在是幂等重放，
  同 ID 不同证据仍拒绝覆盖。
- Guided UI 现在按 PDF 保留并展示 Discovery failure；未找到直接投资组合表的报告不会再
  从阶段 A 静默消失，可从原文件名、年份、策略与失败原因识别选错报告或披露拓扑不适用。
- 太保上市母公司 2023–2025 原生文本双轮 Canary 通过：每年 1 个 occurrence、2 个逻辑分块，
  Golden 全部 MATCH、OCR 0；旧 `中国太保2023年报.pdf`（寿险子公司）作为负对照保持
  `NO_DIRECT_PORTFOLIO_TABLE`。
- 按用户既定边界未运行浏览器 E2E，未执行 Capture/Canonical/Merge，也未写生产 DATA_HOME。

## v6.13 — 2026-08-13（投资组合五拓扑 UI 路由节点 1–3）

- 增加 UI/离线共用的 `PortfolioTopologyExecutionPlan`；五类投资组合拓扑均声明 Direct/Note
  来源、Stage B 认证目标和聚合政策。
- 修复 `DIRECT_COMPOUND_TABLE` 在 Guided UI 中被误显示为附注 Anchor/子表流程的问题。
- 为 Hybrid 增加 Direct + Note 双分支完整性门禁；未全部认证前不生成 Capture Plan。
- 变更 Definition/PDF/口径时清除旧临时 UI 结果；不修改已持久化业务证据。
- 当前状态为节点 3 完成待用户审核；真实 Capture 与浏览器 E2E 未运行。

## v6.13 — 投资组合 DIRECT_PORTFOLIO_TABLES 完整离线基线（2026-08-13）

- 新增 `INVESTMENT_PORTFOLIO_V2`，原生文本定位直接投资组合表，并按单轴、复合双轴、
  同页双物理表保留稳定资产身份；`INVESTMENT_PORTFOLIO_V1` 仅保留历史兼容。
- Stage A 改用投资组合专属拓扑/Golden 门禁；Stage B 按认证物理 ROI、页码、标题与
  资产 ID 认证，不再套用金融投资的固定成员或附注 manifest。
- 平安 2023 已打通正式离线链路至 Canonical/Merge/研究 Excel；两 Capture 均 SUCCESS，
  30 行逐行 Golden MATCH，Merge 值冲突 0、顺序冲突 0。
- 10 份上市母公司年报的直接表矩阵 10/10 MATCH、OCR 0；逐行 Golden 共 209 行。
- 按用户要求未运行浏览器 E2E；附注组件/混合拓扑仍未有上市母公司正向执行基线。

## v6.13 — Registry-scoped Stage A Golden gate repair (2026-08-13)

- 修复投资组合在 Stage A 错套金融投资 Golden 必需成员的阻断问题；Golden Anchor 门禁现按
  Registry Family 显式适用，未注册 Golden 契约的 Registry 继续按机器/PDF 证据审核。

## v6.13 Main Statement Registry & User Registry Governance — 2026-08-13

- 新增合并资产负债表、合并现金流量表两个 Whole-table Registry，以及同一正式链路内的
  `DIRECT_MAIN_STATEMENT_TABLE` 主表认证策略。
- 新增 DATA_HOME 用户 Registry 草稿、校验、原子启用和内置项只读保护；DRAFT/ARCHIVED
  Definition 不能被 Generic Discovery 消费。
- 该版本是 `DEVELOPMENT_CANDIDATE`，仅有定向测试和最小原生文本 Canary；不替代
  v6.12.1 公开预发行，也不声明 E2E、真实 Capture/Canonical/Merge 或 Golden 全链路完成。

## v6.12.1 Full Windows Public Pre-release — 2026-08-12

- 项目、运行时与文档身份统一为
  `PUBLIC_PRERELEASE_UPLOAD_READY / NOT_PRODUCTION_RELEASE_CERTIFIED`。
- 发行采用三个联合资产：公开源码 ZIP、内含 CPython 3.14.5/Tesseract 5.5.3/
  `chi_sim` 的 Windows x64 完整便携 ZIP，以及对应源码/来源伴随 ZIP；三者共同提供
  SHA-256，不得把仅供审阅的早期源码 ZIP 当作最终交付。
- 项目采用 `AGPL-3.0-only`。PyMuPDF sdist、内嵌 MuPDF 1.27.2 及其完整 thirdparty
  源码、LZO 2.10 对应源码与 GPLv3 选择、
  动态可替换的 libiconv 1.18 对应源码/许可证、精确 conda 包/recipe/文件归属、
  Python wheels 和 CPython 输入均已纳入伴随包。
- 公开安全测试 346 项、便携构建契约 2 项、核心导入、Tesseract 版本/语言清单和空
  DATA_HOME 合成 smoke 通过。按用户要求未运行浏览器 E2E，也未运行真实 PDF、Golden、
  Discovery/OCR 或生产 DATA_HOME；因此不是生产发行认证，也不构成 OCR 准确率声明。

## v6.12.1 Windows Portable Pre-release — 2026-08-12（非正式发行）

- 增加 Windows x64 便携包构建脚本：内置 CPython、核心依赖、Tesseract 5.x 和 `chi_sim`。
- 便携启动器使用隔离 DATA_HOME，并将内置 Tesseract/tessdata 置于运行时环境优先级。
- 此条记录最初的便携候选；当前状态以上方 Full Windows Public Pre-release 条目为准。
  真实 PDF、Golden、浏览器 E2E、生产 DATA_HOME 与生产发行认证仍未完成。

## v6.12.1 source-review ZIP — 2026-08-12（非正式发行）

- 新增 `FIRST_RUN.md`，说明新机器的依赖安装、空 DATA_HOME、合成 smoke 和公开测试。
- 生成仅供审阅的源码 ZIP；不包含真实 PDF、Golden、用户 DATA_HOME、缓存、数据库、日志、密钥或本机配置。
- 此处的 source-review ZIP 是历史审阅资产，不是最终 Windows 包；当前联合发行状态以上方
  Full Windows Public Pre-release 条目为准。

## v6.12.1 public-source candidate — 2026-08-11（非正式发行）

- 项目所有者选择 `AGPL-3.0-only`；新增项目级 `LICENSE`，并同步 README、NOTICE、依赖元数据和许可证决策记录。此条当时尚未闭合第三方义务；现已由上方 2026-08-12 联合发行闭包取代。
- 修复公开安全测试暴露的 8 项契约回归：研究任务审核队列路由、原生文本 OCR 审计状态、金融投资 family 外成员、发现行 resolution 返回，以及可再分发的合成多分块不变量探针。
- `v6.12.1` 公开安全测试：`346 passed`。浏览器 E2E、真实 PDF、Golden、Discovery/OCR
  与生产 DATA_HOME 未运行；因此当前可公开预发行，但仍为 `NOT_PRODUCTION_RELEASE_CERTIFIED`。
- 仅修改外部 `public-staging/v6.12.1-public-candidate`，未回写 `releases/v6.11` 或 `releases/v6.12`。

## v6.12 public-source candidate — 2026-08-10（非正式发行）

- 仅在外部 staging 补齐公开 README、数据分发边界、安全/贡献说明、依赖分组、
  `uv.lock`、CycloneDX 1.5 SBOM、空 DATA_HOME 合成样例和公开测试合同；未回写
  `releases/v6.11` 或 `releases/v6.12`。
- 全新 Windows / CPython 3.14.5 环境冻结安装与合成 Smoke 通过。
- 公开安全测试集合为 344 tests / 336 passed / 8 failed；其中 4 项与既有冻结
  `lastfailed` node ID 精确相同，4 项并非该既有集合。测试门保持失败，未改业务语义。
- 从原 staging 的 103 个测试文件/产物中保留 51 个、隔离 52 个；真实 PDF、Golden、
  生产 DATA_HOME、公司专用验收、内部运行器、浏览器 E2E 与编译缓存不进入候选。
- 项目 `LICENSE` 尚未选择；PyMuPDF 的 AGPL-3.0 / Artifex Commercial 双许可兼容性
  在该历史节点尚未闭合；当前状态以上方 v6.12.1 Full Windows Public Pre-release
  条目为准。

## v6.12 — 2026-08-10 合表标签回退与条件排序控件

- 合表来源、合表项目与回收站下拉统一使用安全标签；缺失 `display_name` 时不再显示
  `None ·`，并始终保留稳定 Capture/Merge ID 以避免同名碰撞。
- 国寿 2025“其他权益工具投资”主表、b2、b3 分别显示“按资产类型”“按计量构成”
  与“按上市状态”。中文标题取自既有 classification axis 或 metadata，三个 Capture
  身份保持独立，不重命名 ASCII 安全目录或改写业务数据。
- 创建合表先选择排序策略：默认策略只显示基准 Capture；按年份附注号策略只显示
  基准年份；缺失年份时显式回退默认策略，隐藏基准 Capture 保留稳定首项回退。
- 非 E2E 回归为定向 `22 passed`、受影响集合 `59 passed`。隔离合成浏览器验证在后续
  “跳过所有 E2E”指令前已完成且未创建 Merge Project；该指令后未再运行 E2E。
  `releases/v6.11` 冻结清单复核 333/333，0 missing，0 mismatch。

## v6.12 — 2026-08-09 主表原生优先与页级 OCR 缓存复用

- Research Definition 的主表发现先建立 `ocr_mode=off` 的原生文本 Fast Index；
  只有正式主表尚未被可靠定位，或原生目录指向尚未解析的已审主表页时，才进入
  候选页条件 OCR，不再在主表候选产生前为整本 PDF 执行 `auto/400-DPI` OCR。
- 原生目录证据优先于通用图像密度：已审财务报表目录命中时只识别引用页与直接
  邻页。纯扫描件保留同一 Fast Index 内的两阶段兜底：先用受限页数识别扫描目录，
  再在总计最多 12 页的预算内识别目录引用的主表页；未建立平行 OCR 管线。
- Fast Index 成为生产页级 OCR 缓存的唯一所有者。缓存身份绑定 PDF SHA、OCR
  pipeline、语言、有效 DPI 与预处理版本，不绑定 `auto/selected` 或整批候选集合；
  同时持久化 text、rows、words 几何，供太保空间解析复用。
- 页缓存采用跨线程/进程排他锁、读后合并和原子替换，重叠候选集合不会覆盖已缓存
  页面；OCR 失败页不再伪装为 OCR 成功输出，完整索引命中与页级命中分别审计。
- 版本身份统一为 `v6.12`，正式 resolution 的 `producer_version` 改为引用
  `APP_VERSION`；`releases/v6.11` 保持冻结，不更新根版本指针或生产 DATA_HOME。
- 验证：扩展定向测试 `39 passed, 6 deselected`（6 项均为 v6.11 可复现的冻结基线
  既有失配）；国寿 2025 冷/热 Canary
  `1.170s / 0.449s`，Anchor 89、coverage 1.0、OCR 调用 0；太保 2025 冷/热
  `9.393s / 0.539s`，只 OCR 73/74/75，Anchor 74、coverage 1.0，热运行新增 OCR
  调用 0，跨 Fast Index 键页缓存复用通过。浏览器 E2E 与 12 份年报全矩阵未运行。

## v6.11 — 2026-08-06 研究宽表合计行加粗与浅色底纹

- 按 Canonical `row_type` 语义（`TOTAL / IMPLICIT_TOTAL / SUBTOTAL`）对研究宽表 Excel
  的合计类行加粗，并使用浅色底纹突出汇总关系；识别不依赖中文“合计”文本猜测。
- 不使用行顶边线标记合计，避免误导表分界；样式仅作用于数据行自身。
- 行类型仅作为内存样式元数据传入 `write_presentation_wide_sheet`，
  `research_wide.csv` 与 canonical 机器字段不变；合表项目 `canonical_wide` 展示页
  与独立下载的 `research_wide.xlsx` 复用同一规则。
- 回归：`tests/test_v611_research_wide_export.py` 11 passed；太保合表项目已重新物化验证。

## v6.11 — 2026-08-06 新华其他权益工具投资短表语义轴修复

- 修复新华 2023/2024 “其他权益工具投资”短表因缺少行内 SECTION_HEADER 而被标记
  `classification_axis=UNRESOLVED`、最终按物理 Block 拆行的问题。
- 在 Research Definition 的金融投资成员合同中声明 `classification_axis=ASSET_TYPE`，
  并沿 Discovery → Capture Plan → CaptureRequest → compound 分块器透传；删除按表名/行标签
  硬编码的整表兜底。无权威轴时继续 `UNRESOLVED` fail-closed。
- 相关定向测试 19 passed；现有 Capture 未改写，需正式重新 Capture 后刷新合表。

## v6.11 — 2026-08-06 研究宽表下载名采用合表项目名称

- 研究宽表 Excel/CSV 下载名改为 `<合表项目显示名称>_研究宽表.xlsx/.csv`，
  例如 `太保金融投资 · 中国太保 · 2023–2025_研究宽表.xlsx`。
- 合表详情与完整下载区复用同一命名规则；Windows 非法字符安全替换。
- 合表目录内 `research_wide.xlsx/.csv` 稳定产物名和数据合同保持不变。

## v6.11 — 2026-08-06 合表筛选跨页面重跑保持状态

- 修复合表创建区新增筛选模块的状态生命周期缺陷：修改 `Canonical Table ID`、
  “按年份附注号排序”或基准年份触发 Streamlit rerun 时，不再清空筛选和 Capture 选择。
- 筛选模式、公司/年份/附注表名/研究批次及 selected IDs 改由独立持久状态保存，
  widget 回调在重跑前同步；动态可见列表仅承担展示，不再作为唯一状态来源。
- 不修改 Capture、Canonical、Merge 数据合同及排序算法。

## v6.11 — 2026-08-06 研究宽表中文表头与年报分组样式

- `research_wide.xlsx` 左侧固定表头改为 `附注表名 / 项目 / 单位`，顶部 metadata
  键同步中文化；`research_wide.csv` 与 canonical 机器字段保持不变。
- 年报与数据年度表头统一居中，同报告年度继续横向合并，并以中等粗细边框强调
  年报组边界及数据年度切换；同时隐藏网格线、冻结表头与左侧三列、统一列宽和金额格式。
- `附注表名 / 项目 / 单位` 固定表头之间同步使用中等竖线，粗线仅限表头区域。
- 复用唯一 `write_presentation_wide_sheet` 模板，合表项目展示页与独立研究宽表一致。

## v6.11 — 2026-08-06 跨年度 Canonical 行按语义轴对齐

- 修复 Capture-local `table_block_id` 被用作跨年度 Canonical key 与机器宽表 pivot index，
  导致太保同一 `member_table / classification_axis / row_path` 按年度拆行的问题。
- 已解析语义轴跨 Capture 对齐；`UNRESOLVED` 轴继续按 Block fail-closed 隔离。
- 物理 Block 身份保留在 Canonical Long provenance，宽表多来源 lineage 显示为 `MULTIPLE[...]`。
- 旧 Merge Project 可直接重新物化，无需重抓 Capture。

## v6.11 — 2026-08-05 太保 Stage A OCR 千分位点误读修复

- 扫描版主表 OCR 把千分位逗号误读为点（`4.986,274`、`611.682.378`）时，
  空间金额观察正则不再丢弃当前期值；带点读数按列绑定为 BBox Anchor 观察，
  太保 2024 debt_investment、2025 fvtpl_assets/other_debt_investment 的
  Golden 门禁不再误报“当前期缺失”。
- 回归：`test_v611_cpic_spatial_anchor_observation.py` 新增带点读数与
  2024/2025 门禁用例（7 passed）；邻接 63 passed。

## v6.11 — 2026-08-05 合表顺序改为按所选年份附注号排序

- 新增排序策略 `NOTE_ORDINAL_REFERENCE_YEAR`：用户选择基准年份后，按该年年报
  附注号（note ordinal）排序成员表，表内行序保持该年 Capture 顺序；
  无该年来源的成员按 member_table_order 追加末尾。
- `build_structural_order` 支持新策略并把 `note_ordinal` 写入
  `merge_structural_order.csv`；`refresh_merge_project` 支持
  `order_policy` / `reference_report_year` 参数并持久化到 manifest。
- 合表页“合表顺序策略”提供基准年份下拉与“应用基准年份并重新物化合表”。
- 旧策略 `REFERENCE_CAPTURE_PRESERVE_WITH_CONTEXTUAL_INSERTION` 保持默认兼容。
- 回归：`tests/test_v611_note_ordinal_merge_order.py` 3 passed；邻接 44 passed；
  自适应表头脚本 8 项 PASS。

## v6.11 — 2026-08-05 合表输出新增「研究用宽表」

- `table_merge.py` 新增 `build_research_wide_frame`：研究宽表只保留
  `member_table` / `canonical_item` / `unit` 与实际数据列。
- `write_presentation_wide_sheet` 支持自定义 sheet_name；
  `write_merge_outputs` 新增 `research_wide.csv` 与 `research_wide.xlsx`
  （多层/合并表头架构与展示版一致）。
- 合表区新增“下载研究用宽表 Excel / CSV”入口（含多层表头下载列）。
- 回归：`tests/test_v611_research_wide_export.py` 3 passed；邻接 43 passed；
  自适应表头脚本 8 项 PASS。
- 研究用宽表的 `member_table` 改用注册表中文显示名（如 `贷款`、`债权投资`），
  不再显示系统标准 ID（`legacy_loans`、`debt_investment`）：`MergeService.create`
  从 `family_members` 构建显示名映射并写入合表 manifest，
  `write_merge_outputs` 在导出研究宽表时应用映射；canonical_wide 仍保留系统 ID。

## v6.11 — 2026-08-05 系统与迁移页「旧数据完全清除」功能

- 新增 `services/data_cleanup_service.py`：只读预览（表行数/目录文件数）、
  强制备份（metadata.db + manifest + SHA256）、单事务清空 Registry 业务表、
  归档 DATA_HOME 派生产物到 `backup/old_data_clear_<时间戳>/` 并重建空目录，
  输出清除报告。
- 支持两种清除范围：`all`（认证＋抓取＋合并全量业务数据）与 `capture`
  （仅抓取记录，保留 occurrence/Anchor/子表候选/认证清单/CertifiedChildTableLink）。
- “系统与迁移”页新增“旧数据完全清除”区块：需输入确认口令 `DELETE-OLD-DATA`
  才可执行；默认保留 Schema、Research Definition、表族/成员、config/Taxonomy、
  Golden 与 PDF；可选同时清除上传 PDF。
- 回归：`tests/test_v611_data_cleanup_service.py` 8 passed；邻接 49 passed。

## v6.11 — 2026-08-05 Stage B 重复认证附注容器复用与 fail-closed

- 同一 PDF/附注容器重复认证时，自动认证改为采用既有 certified links（内容等价
  且 PDF digest 一致），不再因 `NOTE_TABLE_INVENTORY_ID_MISMATCH` 产生 0 条
  certified links 的死路。
- 阶段 A 认证零产出时 UI fail-closed：明确报错，不再静默回退到历史执行会话，
  避免“只显示/抓取 2023”的误执行；对应 incident 见 INC-017。

## v6.11 — 2026-08-05 Stage B 首次提交持久化与展示术语收口

- Stage B 面板“确认逻辑表并抓取”现在把只读预览所用的同一份
  `certified_links` / `source_pdf_map` / `plans` 回传
  `create_execution_batch`：首次使用（无既有 session 行）也能在显式提交中
  原子落库计划、session 与 scope 后执行，不再落入
  `STAGE_B_EXECUTION_SESSION_NOT_FOUND`；已恢复 session 仍按 `session_key`
  幂等提交。
- Stage B 抓取逻辑表复选框改用共享展示词汇（附注主明细表 / 附注补充分析表），
  持久化枚举 token 不变；对应 incident 见 INC-016。

## v6.11 — 2026-08-05 Guided self-selection 与 CaptureBundle 身份收口

- Guided request 改为自选择：`PRIMARY_ONLY selected_logical_table_ids=[]`；每个
  `SELECTED_NOTE_TABLES` request 只携带自身 certified logical-table ID；filing union 只
  核验用户显式选择的 supplementary 集合，不再向每个 request 传播。
- CaptureBundle immutable version identity 纳入 note container、certified logical table、
  scope signature、CaptureRequest 与 root Capture；LogicalAsset identity 纳入 certified
  logical table 但不纳入 scope，使逻辑资产跨策略稳定、执行版本仍可审计区分。
- 同一 bundle version 重放时，在一个事务内替换全部 children，并重建唯一连续的
  `child_order=0..n-1`。Merge 对每个 bundle 严格要求唯一 `child_order=0` root，缺根、
  双根、乱序、空洞或 requested root 不一致均 fail-closed。
- fresh `PRIMARY_ONLY` 正式 Merge 为 49 roots → 90 assets，current Golden v3
  883/883 cells；fresh supplementary 正式 Merge 为 14 roots → 18 assets，Golden
  322/322 cells，冲突 0。两套结果均证明 certified scope 当前无阻断。
- 覆盖状态未被扩大：`ALL_NOTE_TABLES` 仅新华 2024 为 `CLEAR`，其余 11/12 为
  `PENDING`；认证 true `CONTINUATION_SEGMENT` 为 0；Streamlit 状态为 `NOT_RUN`。

## v6.11 — 2026-08-04 CaptureBundle 正式 Canonical/Merge 全量展开

- 修复正式 Merge 仅消费调用方传入的 bundle root Capture、遗漏同 bundle secondary
  logical Capture 的根因；49 个 root 现在从 registry 按 `child_order` 展开为 90 个
  Capture assets，全部资产进入 source lineage。
- bundle 必须为 `READY`、child 必须为 `CAPTURED`，请求项必须是 `child_order=0` 根；
  重复 bundle/child、缺失资产、repository 乱序，以及 bundle、认证 logical table、
  family/member、PDF ID/SHA256、`table_block_id` 身份漂移均 fail-closed。
- 不再通过排除整个 derived child Capture 修正合表。raw Capture graph 的 902 个数值全部
  保留，其中 18 个 `DERIVED_REJECTED_NON_BLOCKING` 与 6 个
  `SUPPRESSED_BY_EXPLICIT_TOTAL` 按 row/cell 证据排除，Canonical/Merge 选择 878 个
  SOURCE 数值；排除键和逐格身份核验结果写入 Merge manifest。
- current Golden v3 共 883 cells（878 numeric + 5 DASH），正式 fresh Merge 为 90/90
  source identity 完整、878/878 numeric、`VALUE_CONFLICT=0`、review/blocking conflict=0；
  正式数据库 SHA256 前后一致。

## v6.11 — 2026-08-04 新华 2023 ECL 多级表头身份修复

- 新华 2023 p188/p189 的 ECL 补充表将 `第三阶段` 单行父标题向下绑定到第三金额车道，
  保留其三行叶标题；`合计` 车道不再继承第三列的叶标题片段。
- 本地表头起点从第一条多车道叶标题向上扩展到紧邻、无叙述标点且与金额车道对齐的
  稀疏 group header；长表头和叙述行不改变既有 dense-header 发现。
- 多 parent hit 的 Voronoi 分区新增本地 lane-gap 距离门禁；单个命中若已明确贴近某条
  lane，只绑定最近车道，避免把局部叶标题扩散到空白相邻列。
- 修复不按公司、年份或页码分支；真实新华 2023 fresh `SELECTED_NOTE_TABLES` 为
  6/6 SUCCESS、review=0、quality pass，正式 DATA_HOME SHA256 不变。

## v6.11 — 2026-08-04 国寿 2023 贷款主表/补充表 Golden 身份修复

- canonical PDF reader p174 的 `8. 贷款` 六行余额表保持 `PRIMARY_TABLE`；p175
  `(b) 其他贷款` 到期期限表重置分类轴，迁移为独立 `SUPPLEMENTARY_TABLE`，不因标题
  “（续）”伪造 continuation。
- 12 个金额仅在 Golden 表身份间迁移，金额、期间与页码均由 SHA 绑定 PDF 文本层和
  180 DPI 页面原图直接核验；`PRIMARY_ONLY` 值断言 94→82，supplementary 54→66。
- `infer_company_year()` 通用清除“报告年份 + 年 + 年度报告”文件名后缀，修复展示字段
  `中国人寿年`，不修改权威 `company_id`。
- `raw_item` 继续保留 PDF 原文；normalized identity 通用清除行尾脚注引用。文本父组按
  子行缩进与 subtotal/total 闭合恢复，覆盖多子项组和小计后的单子项嵌套组，grand total
  不再继承上一分类轴。
- Golden 只作独立验收，不反向生成 runtime manifest；supplementary 自动认证必须由
  candidate inventory 的 bbox/period/header/amount-lane 完整签名与明确 reset relation 支撑。

## v6.11 — 2026-08-04 Stage B 抓取范围持久化与同附注多表策略

- Stage B 抓取前提供 `PRIMARY_ONLY`、`PRIMARY_WITH_CONTINUATIONS`、
  `ALL_NOTE_TABLES` 三种范围；主表续表策略明确不包含补充子表，全部子表策略才包含
  supplementary 及其各自续表。
- CaptureRequest 增加 typed scope 字段；`stage_b_execution_sessions.capture_scope_json`
  成为持久化真源，registry schema 12→13 幂等迁移。旧 session/request 默认
  `PRIMARY_ONLY`，提交后 scope 冻结，Streamlit 渲染不写业务状态。
- scope 只沿 ChildCaptureExecutionService、Guided、CaptureRequest、Orchestrator、
  CaptureService 正式单链传递。执行层在 materialize 前按通用 segment relation 过滤，
  排除段保留 manifest，不创建伪 child capture。
- `PRIMARY_ONLY` 只有显式 scope boundary evidence 才把已确认续表降为非阻断
  `CONTINUATION_EXCLUDED_BY_POLICY`；包含策略下未决 continuation 以
  `CONTINUATION_UNRESOLVED` 阻断，证据不足一律 fail-closed。
- 同附注内具有独立披露边界且 header/lane/axis 重置的表按 `SUPPLEMENTARY_TABLE`
  分类；标题“（续）”仅为弱证据。period 重置本身不拆逻辑表：新华 2025 p197 的
  2025/2024 区块保持一张 supplementary。只有真正分页截断且同一逻辑表未完结的段才
  建立 continuation relation；禁止按公司名分支或横向拼接不同列拓扑。
- locator 与 Discovery 统一拒绝 `candidate_page <= main_statement_page`，该门禁覆盖
  Tier 1/2/3，避免 fallback 再次选中主表页。
- stacked vertical-period Capture 同时登记逻辑 `block_id` 与共享
  `physical_segment_id`；认证 manifest 只比较一次共享物理段，期间块仍按各自列 ordinal
  materialize。修复中国人寿 2023 p177 在 manifest 已认证却无法进入 Scope 的
  `CERTIFIED_LOGICAL_TABLE_SEGMENTS_REQUIRED` 阻断。
- 认证段清单始终完整保留；v2 `PRIMARY_ONLY` 只 materialize 逻辑表根段，续段进入
  excluded manifest，只有包含续段的策略才展开认证链。严格计划按
  `PRIMARY_TABLE` 优先于 `SUPPLEMENTARY_TABLE` 排序，避免独立补充表失败时错误跳过主表。

## v6.11 — 2026-08-04 三家公司 Stage B 子表跨表边界、垂直期间与完成态投影修复

- 下一附注识别新增“年份限定标题”窄豁免；账龄行、金额行及破折号占位行仍不得
  冒充 peer-note 标题。
- CertifiedChildTableLink 的页跨度只限制入表 ROI，不再禁止只读边界前瞻；若下一页
  标题前仍有续表表体/金额，拒绝硬确认，避免以标题越过被截断的真实表体。
- 重复年份双金额簇不再压成单一 header leaf；新增 `摊余成本/公允价值` measure，
  period+measure 共同构成唯一列维度。
- 垂直期间块改为全 ROI 预扫描：支持第二期间首次出现在下一页、重复表头和跨页续表，
  持续复用正确 `column_offset`、`block_id` 与完整声明列集合。
- 完整年报页脚保留原始证据但排除表逻辑；Header Review 往返保留 measure、期间、
  页脚排除及审计字段；勾稽按 `column_ordinal` 对齐，excluded footer 不再改变 terminal。
- CaptureCompletionService 在权威 reducer 事务成功后，将同一 DecisionResult 单向投影回
  `capture_metadata.json`；不调用第二套 readiness engine，消除 secondary child 的
  `UNASSESSED/PENDING_CAPTURE_COMPLETION` 陈旧文件状态。

## v6.11 — 2026-08-04 父子行勾稽不一致降级为合表警告

- `MISMATCH` 继续保存为机器勾稽事实与逐列差额证据，但 reducer 将它和旧 artifact
  的 `WARNING` 统一映射为非阻断 `RECONCILIATION_WARNING`。
- `capture_readiness` 不再将 `MISMATCH` / `WARNING` 写入 merge blockers；仅 `FAIL`
  保持阻断。页末边界推断仍要求勾稽 `PASS`，未放宽该安全条件。
- ADR-007 取代 ADR-006 中“勾稽不一致阻断合表”的决策；不实现通用父子行识别。

## v6.11 — 2026-08-04 勾稽语义拆分：MISMATCH 阻塞 / WARNING 非阻塞

- 块级 `_reconciliation`：任一算术检查未通过的状态由 `WARNING` 改为 `MISMATCH`
  （已证实的数值不一致）；PASS / NOT_TESTABLE 语义不变。
- reducer 与 capture_readiness：状态 `WARNING`（旧 artifact 兼容）/ `MISMATCH` / `FAIL`
  触发阻塞码 `RECONCILIATION_MISMATCH`（merge blocker `V69_RECONCILIATION_MISMATCH`）；
  `RECONCILIATION_WARNING` 不再进入 `blocking_issues`，在评审严重度中回归非阻塞（LOW）。
- 新增评审目录/路由映射 `RECONCILIATION_MISMATCH`；`normalize_review_reason` 区分 MISMATCH。
- 新增回归测试 9 条（PASS/MISMATCH/NOT_TESTABLE、reducer 阻塞码、旧 WARNING 兼容、
  目录与归一化）。

## v6.11 — 2026-08-04 侧页印刷页码杂音分类（新华年报“07”模式）

- 新增 `_mark_side_page_number_noise`：左侧/右侧边距、无标签、单短整数、
  位于表格 x 带之外且与印刷页码匹配的 token 标记为
  `row_role=PAGE_NUMBER_NOISE` + `excluded_from_table_logic=true`；
  与页底尾页页码分类互补，覆盖新华年报“侧页 07”这类页中边距页码。
- 原始行保留在机器证据中；拓扑、数据列复核、合表输出均排除。
- 新增回归测试 5 条（标记/印刷页码不匹配/表带内不标/带标签不标/双列拓扑排除）。

## v6.11 — 2026-08-04 边界状态优先级 / BoundaryReason 契约 / 表尾页码杂音修复

- `BoundaryReason` 枚举统一解析器与消费端 reason 契约；解析器输出
  `next_note_ordinal` / `next_peer_heading` / `same_page_footer_fallback`，
  ordinal 保留在 evidence，新增 `next_note_verified`；消费端归一化兼容旧字符串。
- `derive_boundary_status` 重构为四层优先级：人工裁决（`boundary_status_source=
  HUMAN_ADJUDICATION`）> 机器强证据（next_note HIGH → `HARD_BOUNDARY_CONFIRMED`，
  可推翻机器预置 REVIEW_REQUIRED）> 复合证据（footer fallback + 已核验合计 +
  仅杂音后续行 → `SOFT_BOUNDARY_CONFIRMED`，MEDIUM 置信度 + COMPOSITE_EVIDENCE）>
  机器默认 REVIEW_REQUIRED 兜底。
- 表尾页码杂音复合分类（终止行后 + 无标签 + 单短数字 + 底部区域 + 匹配印刷页码），
  原始行保留并标记 `row_role=PAGE_NUMBER_NOISE`、`excluded_from_table_logic=true`，
  在拓扑、数据列复核与合表输出中排除。
- 新增回归测试 14 条（状态优先级/契约/杂音/审计差异/reducer 门禁）。

## v6.11 — 2026-08-04 空金额列 CSV 防护修复（memo-only 表块不再使 job 失败）

- `capture_library._rewrite_capture_excel` 引入 `_read_csv_optional`：缺失或
  空文件（含 utf-8-sig 空 DataFrame 写出的 5 字节 BOM+CRLF）按空表处理，
  不再抛 `EmptyDataError` 导致整条抓取 job FAILED。
- `reconciliation.write_reconciliation_audit` 对空/缺失长表同样防护，并补齐
  空结果 reconciliation_summary.json。
- 背景：其他权益工具投资 2023 附注页含纯备忘行块（如“见附注七、40。”），
  该块无金额列 → wide CSV 仅 BOM → 修复前 `GUIDED_497d75c577d7` 批次第 4 条
  job 失败，父运行停在 UNASSESSED / PENDING_CAPTURE_COMPLETION。
- 新增回归测试 5 条（缺失/5 字节/正常 CSV、_rewrite_capture_excel、reconciliation）。

## v6.11 — 2026-08-04 表头拓扑占位符对齐修复（中国太保“-”披露）

- `TableCell` 新增 `cell_state`（NUMERIC / PLACEHOLDER / EMPTY / UNPARSEABLE）审计字段；
  纯破折号 token 且已对齐金额列的单元格标记为 `PLACEHOLDER`，永不转换为数值。
- `_topology()` 改为“按已对齐金额槽位”推导：优先信年度表头列数，占位符计入占用槽位；
  真正缺列（无 token/无 bbox/无占位证据）仍判歧义。拓扑证据扩展
  `expected_numeric_columns` / `header_labels` / `parsed_numeric_widths` /
  `occupied_slot_widths` / `placeholder_tokens` / `placeholder_cell_count` /
  `unresolved_cell_count` / `column_alignment_consistent` / `topology_reason`。
- `CaptureDecisionReducer` 门禁未放宽：`consistent=false` 仍触发
  `HEADER_TOPOLOGY_AMBIGUOUS` 阻塞。
- 新增回归测试 14 条：正常双年度、单/双侧破折号、双侧破折号、负数、横线、真缺失、
  真实反例、reducer 门禁，以及太保 2025 债权投资（放行）与交易性金融资产（仍阻塞）真实资产 Canary。

## v6.11 — 2026-08-04 单位声明解析修复（中国太保）

- `DocumentContextResolver` 单位正则支持“金额单位**均**为人民币X”写法并增强空格兼容
  （`金额\s*单位\s*(?:均\s*)?(?:为|以|：|:)` 等），修复中国太保 2023–2025 单位继承缺失
  导致的误报 HIGH「单位不确定」（`UNIT_UNCERTAIN`）。
- `DocumentContext` 新增 `unit_source_text` 审计字段（保留原始命中文本与来源页），
  `as_dict()` 与 declarations 同步携带；不改变既有字段语义。
- 新增三层回归测试：正则正/负例、太保 2023 第 169 页真实页头集成、CaptureDecisionReducer
  门禁（无单位证据仍被阻塞）；真实 PDF Canary 覆盖 2023–2025 三份年报。

## v6.11 — 四公司 Child 历史隔离与阶段 B 重认证 Hotfix

- 修复阶段 B 把完整 OCR 源行误用为成员显示/检索名称的问题。现在由 `canonical_concept_id` 从 Research Definition 获取标准标题与 aliases；源行保留为审计证据。OCR 数值以只读定位候选展示，绝不写入认证主表金额或勾稽。Child Discovery 升级为 V3，旧缓存与旧 Streamlit 会话映射将被明确隔离，需重新认证阶段 A。
- 收敛生产 OCR profile：GUI 主表发现、条件 OCR、语义兼容索引和离线 12 份认证矩阵统一使用 `FINANCIAL_TABLE_400DPI_V1`（`chi_sim+eng`、400 DPI、质量阈值 0.5、原生字符阈值 40）。400 DPI 已在 Fast Index 缓存键中隔离旧 300 DPI 缓存；不迁移 DATA_HOME、Capture 或人工认证。
- 收敛生产 Document Index：`build_fast_index()` 成为唯一 OCR/缓存执行器；`build_text_index()` 保留原有语义返回合同但改为 Fast Index 适配器；`conditional_ocr_primary_statements()` 保留有界页选择策略并在生产路径委托 Fast Index 的 `selected` 模式。注入式 OCR provider 仅保留给既有确定性测试。
- 统一 OCR TSV 几何随 Fast Index 语义适配进入主表解析。修复“父行+多个带附注子项”被过早降级为单一附注证据的问题，保留更强的 `EXPLICIT_PARENT_WITH_CHILD_NOTE_CLUSTER` 审计语义。
- GUI 阶段 A 改为复用 OCR-aware Fast Index，并保留其 TSV token 几何；扫描版主报表不再因原生文本为空而只显示前置摘要页。中国太保 2023 年报已验证定位到 PDF 第 74 页，恢复附注七-10 至附注七-13 四个当前口径成员。
- 中国太保扫描表的空间行重建接入主表家族解析；当缺少可读的“金融投资”父行但当前口径成员簇完整时，先以可审计的 `IMPLICIT_MEMBER_SET` 解析当前成员，避免错误优先退回同页旧口径项目。
- 新增受控归档工具：按 PDF SHA256 隔离中国平安、新华保险、中国太保及中国人寿 2023–2025 年报的 Child 发现、认证链接、相关索引与失败缓存；保留原始 PDF、Golden Corpus 与可恢复的数据库快照。
- 修复 Child 概念创建与阶段 B 发现的状态门禁不一致：`UNRESOLVED` 为可审核状态，不再被错误视作已证明的非当期/非表族成员；仅显式的比较期、表族外成员会被跳过。
- 修复中国太保等“标签行与金额行分离”主表版式：解析器保留上一物理行的项目标签作为子项身份，不再将下一行金额误写为 `raw_member_label`。
- 父子边界改为由已识别的表族外结构行关闭，不再以原始 PDF 文本行距离作为边界；修复新华保险 2023 年“其他权益工具投资（附注四-14）”被错误排除的问题。
- 新增上述两类回归测试。OCR/文本索引只能提供定位与结构证据，不会把 OCR 数值写入认证金额。

## v6.10 — 最终数据列与人工审核可执行性 Hotfix

- 修复 Structured Capture 的 `rows[].cells` 未被最终数据列检查读取，导致完整的双期间数据被误报为 `0/N` 末列 token。
- 末列检查仅统计具有来源数值的适用行；分别披露排除的派生合计行和无数值污染行，边界污染继续由独立边界审核处理。
- 最终数据复核新增带理由和证据的“人工覆盖确认警告”，机器证据保持不变，人工裁决可真实解除对应审核任务。
- 重算不再遗留已经被新算法证明无效的 OPEN 机器问题；历史问题以 `MACHINE_RECHECK_CLEARED` 保留审计。
- 修复 REVIEW_REQUIRED 已注册版本永远不能成为 current、而最终认证又要求 current 的治理死锁；历史无-current逻辑资产会选择最新有效版本并修复替代链。
- “附注容器与表块”新增 Capture 末尾边界人工确认，可选择最后有效数据行、重建正式输出并解决 `PDF_BOUNDARY_REVIEW`。

## v6.10 — 批次抓取到逻辑资产审核闭环 Hotfix

- 明确区分“跨逻辑资产的批次待审核 Capture 队列”与“单个 Logical Asset 的 Capture Version 历史”，修复用户只能看到一个版本候选却无法遍历整批 Capture 的交互断点。
- 普通整表批次与研究引导批次在作业终态后均计算 Capture 质量；默认选中全部 `REVIEW_REQUIRED` 表，并可一键送入逻辑资产工作区逐张审核。
- 逻辑资产工作区新增批次审核队列、上一张/下一张和返回批次监控；抓取成功不再被误表述为已认证可合表。
- 逻辑资产工作区与数据资产管理均新增研究批次筛选；Capture 列表通过 `research_batch_members` 关系解析批次，不复制伪字段。
- 修复默认逻辑资产查询及版本下拉遗漏 `TRASHED` 的问题；历史、归档、废除、被替代版本仅在用户显式开启历史显示时出现。

## v6.10 — 主报表候选发现条件式 OCR Fallback Hotfix

- 主报表候选发现保留既有文本层索引与评分路径；仅在目标主报表不存在高置信文本候选时，才以受限页集合执行 OCR 页面定位。
- 新增页面模态判别、目录/财务章节邻近页优先级、图片型页面候选与 OCR 审计字段；OCR 只补充页面文本，不提取、生成或修改财务金额。
- 默认禁止全文件 OCR：候选集若覆盖整份多页 PDF，会保留高优先级子集并记录截断；单页文档在默认策略下保守 abstain。
- OCR 不可用或未获得合格候选会返回明确状态并进入审核/未解决路径，不会抛出导致 Discovery 中断的异常。
- OCR 与文本路径同页命中时按主报表/项目/附注/页码聚合证据，避免将同一候选重复交给人工审核。
- 新增条件式 OCR 定向测试；未运行全历史回归，OCR 引擎真实安装状态以运行环境为准。

## v6.10 — Anchor / 子表映射与认证抓取热修复

- 唯一的满分（UI 显示为 1.00）且通过硬门禁的主报表 Anchor 会直接预选；次优高分候选不会仅因分差小于通用阈值而强制人工仲裁，满分并列仍保留人工审核。
- 选择非推荐 Anchor 或子表时，“覆盖原因”改为可选审计说明，不再阻断认证。
- 单一可行的子表映射默认在审核表单中选中，但仍需用户点击认证，绝不自动执行抓取。
- 修复认证子表将 Registry `member_table_id` 误当 PDF 表标题传给严格空间抓取的问题；现在使用已认证候选的 `raw_heading` 作为抓取查询，同时保留 member id 作为研究身份，避免误报无表头/边界失败。
- 认证映射会把主表子项的附注引用一并写入证据和 Capture Plan；严格空间抓取优先用该引用确定附注边界，并把已认证目标页范围作为最大扫描边界，不会绕过 Table Boundary Resolver。
- 修复边界解析器将 `93.15亿元` 等金额误识别为“附注93”的伪下一附注问题；缺失当前附注号时不再伪造硬边界，存在当前附注号时只接受近邻附注作为同级边界。
- 修复认证标题含 `10. / 11. / 12.` 或 `(3)` 等附注/小节序号时，严格空间抓取将整段原文误作查询标题而无法识别表头的问题；原始标题继续保留为证据，执行查询使用去序号标题。
- Financial Note Index 升级为 V2，可把同页分行的裸序号 `9.` 与下一行正式标题组合成同一附注标题；Discovery V2 会失效旧缓存并重新执行严格分级召回。
- 子表映射新增“主表附注号与候选附注号一致”硬门禁；旧认证若发生 `附注八-9` 对 `小节3` 的不一致，将隔离为重新审核，不再进入 Capture Orchestrator。
- 同步批量抓取改为逐子表报告失败，单个旧认证关系异常不会中断其余已认证表的执行。

## v6.9 — Financial Extraction Engine V2 and Research Definition Registry

- Hotfix：修复 Anchor 已人工认证后，被下一次歧义候选重新评分批量降级为 `ANCHOR_SELECTION_REQUIRED`；认证审计现为持久真源，机器推荐刷新不得覆盖人工认证，且可自动修复漂移的物化状态。
- Hotfix：修复新一轮 Discovery 后阶段 B 继续引用上一轮未认证 occurrence、生成计划时触发 `UNSELECTED_ANCHOR_NEVER_MATERIALIZES`；新发现会清空下游会话状态，认证后从 Registry 重新加载正式 Anchor。
- Hotfix：阶段 A 默认展示候选主报表 PDF 原页、父子项金额/附注编号和中文人工核对点；机器评分权重与硬门禁降至折叠的高级信息。
- Hotfix：Statement Anchor 候选先去重、再按可审计证据评分并按 PDF/口径保守单选；低分或歧义候选不预选，预选与人工认证严格分离。
- Hotfix：统一检查中心新增结构化 Review Issue/Task、审核进度、表头交互复核、最终数据列与末列专项检查；普通用户不再依赖手写 JSON。
- Hotfix：人工任务裁决、Anchor 认证与正负 ML 标签均追加保存审计记录；最终认证和 Merge 增加研究定义、定义版本、表族、口径与 current 身份硬门禁。
- SQLite schema 升级至 11；迁移为幂等增量，不修改历史机器证据。
- 新增 NoteContainer、TableBlock、CaptureBundle 及独立子 Capture 审计模型。
- 新增主报表 Statement Anchor 几何抓取，父行允许无金额并保留连续子项附注入口。
- 新增布局证据图、保守多表分段、表头拓扑及勾稽质量门。
- 将“逻辑资产工作区”收口为唯一单资产详情与审核中心；审核收件箱仅负责队列、筛选和路由，旧“附注多表检查”降级为兼容跳转。
- 新增稳定 InspectionRoute、统一 CaptureInspectionPanel、统一 PDF 证据面板与统一审核动作服务；合表来源也直接路由到同一检查中心。
- 人工确认、驳回、未解决与覆盖裁决采用版本级原子事务，并同步当前版本、收件箱、生命周期、Bundle 聚合状态及合表资格。
- 结构修改创建不可变的新 Capture Version；旧版本保留为只读历史，认证新版本后旧 current 自动 supersede。
- 新增版本化 ML 标签合同及可解释的层级回退排序；不涉及金额生成。
- v6.9 初始发布使用 schema 10，当前 hotfix 使用 schema 11。

## v6.8

- 修复研究引导抓取页面仍访问已移除 `generic_discovery.PRESETS` 的启动错误；可选知识包现完全来自 Research Definition / Table Family Registry，并以不可变 `discovery_context` 传入通用发现服务。
- 所有抓取入口统一为 CaptureRequest / CaptureOrchestrator。
- 移除 PRESETS 运行时变异，改为依赖注入策略。
- 新增逻辑资产、不可变 Capture 版本、生命周期审计、审核收件箱和归档恢复。
- 合表默认只接受 current certified active 版本。
- Runner 新增显式 join/shutdown，成功状态要求注册确认。
- 新增抓取中心、审核收件箱和逻辑资产工作区。

## v6.7.x — Adaptive Research Wide Preview & Legacy Upgrade Hotfix

- 自适应多层表头预览改为两种共享同一维度策略的视图：交互式预览直接复用数据资产管理的原生 `st.dataframe` 工具栏（查看、下载、搜索、全屏）；严格多层表头视图作为展示版 Excel 的视觉基准。原生组件的单层可读列名仅是交互呈现，不改变 Canonical Long 或 CSV 的机器身份。
- 修复下载的展示版 Excel 仍显示 `COL_00001` 等机器列 ID：`canonical_wide` 工作表现在只写人类可读的多层/合并表头和数据；稳定列 ID 仅保留在机器 CSV 与 `column_dimensions` 映射中。
- 已存在的合表若由旧展示版导出器生成，Canonical 宽表页会要求先“重新生成展示版 Excel 与宽表派生产物”，避免下载到与预览不一致的旧文件；新增当前预览 HTML 下载。
- 在“Canonical宽表 → 自适应多层表头预览”内直接增加下载入口：可下载含真实多行/合并表头的 `merge_project.xlsx`、机器稳定列 ID 的宽表 CSV，以及 `column_dimensions.csv` 维度映射；不再要求用户切换到独立下载页才能导出当前预览。
- 修复 Research Wide GUI 仍以旧式平面 CSV 方式显示的问题：现在直接读取 `COL_xxxxx + column_dimensions.csv`，使用与 Excel 导出一致的自适应表头策略渲染多层预览。
- 单公司、单口径、单单位、年度数据会将公司/口径/单位/期间移至元数据区，主表默认显示“报告年 → 数据年（已重述）”。多公司、混合口径、混合单位或必须区分原始/重述的同年份数据会自动提升相应表头层级。
- 新增明确的“升级旧合表为 v6.7 自适应宽表”入口：仅重建派生 Long/Wide/Excel/维度映射，不修改原始 Capture、机器证据或人工审核。
- 旧版宽表不再被误判为可用 Canonical Research Wide；若源 Capture 已有历史单位错误，升级仍会提示必须重抓原 PDF，绝不猜测金额。
- 修复旧合表升级时 `document_year` 被 CSV 读为 `int64`、随后写入规范化字符串年份而触发 Pandas 3 `TypeError` 的问题；升级器现在仅预先规范化期间身份字段，金额列保持原样。
- 修复旧合表升级在 Pandas nullable string / `pd.NA` 场景下清洗期间字段、scope、restated 标记时触发 `boolean value of NA is ambiguous` 的问题。

## v6.7.x — 新华保险 2023 附注 11—14 Capture Quality Hotfix

- 修复同一附注页“主余额表 + 后续信用损失变动表”被误视为一张表、进而触发表头列数冲突的问题；空间表头裁判现在只以首个已闭合主表的数据窗口为依据。
- 主表在合计/小计后出现独立说明文字时，自动截断为可审计的首表边界；不再把后续不同列拓扑的披露块混入同一 Note Detail Capture。主表后的“其中”拆分行仍会保留。
- 修复脚注文本中出现“本集团/本公司”被误识别为表头口径、使真实数据行被跳过的问题；表头上下文仅在紧邻表头的区域内生效。
- 新华保险 2023 年报附注 11、12、13、14 的首表均可完成空间抓取，并取得 `HARD_BOUNDARY_CONFIRMED + AUTO_CONFIRMED`；附注 12、13 的后续信用损失准备变动表不再污染主明细表的列结构。

## v6.7.x — Direct Ordinal Note Reference Hotfix

- 支持“附注八 + 11”章节式引用与“附注 + 11”直接序号引用；后者标准化为 `附注11` 并标记 `EXPLICIT_ORDINAL_COLUMN`。
- `NoteReferenceResolver` 可在没有 section 的情况下，以“附注序号 + 科目语义 + 表格特征”生成 `ORDINAL_SEMANTIC` 候选；认证前仍不允许执行抓取。
- `8/59(1)` 等交叉引用标记为 `CROSS_REFERENCE_REVIEW_REQUIRED`，保留原始证据且不伪造单一附注目标。
- 移除 `pdf_evidence.py` 中对“附注八”的固定假设，改为读取主报表实际附注列头。
- 修复 Generic Statement Discovery 未处理“项目行与附注序号分行提取”的问题；新华保险 2023 年报 PDF 109 的 `11—14` 现可生成可认证候选，目标明细页为 PDF 187—190。
- 修复 `GenericStructureParser` 未向审核 UI 物化 `note_target_candidates` 及主表策略变量遗漏，避免出现“未找到可认证附注目标”。

## v6.7 — Registry-Driven Generic Research Data

- 新增可持久化、可审计、可版本化的 Research Definition / Table Family / Member / Discovery Strategy / Metric Mapping Registry。
- 新增 pattern-driven Generic Discovery Engine，支持主表多附注、单项附注、直接附注表族和直接披露策略；金融投资不再是 UI 中的独占特判。
- 新增 `investment_portfolio` 第二个 Golden Family，包含“按投资品种”和“按会计计量”两个独立直接披露 member tables。
- 新增 Accounting Semantic Parser v2：统一 `SECTION/DETAIL/SUBTOTAL/TOTAL/IMPLICIT_TOTAL/ADJUSTMENT/MEMO_TEXT` 等 row-role ontology，推导语义不覆盖机器证据。
- Canonical Wide CSV 切换为稳定 `COL_xxxxx` 列 ID + `column_dimensions.csv`；Excel 输出观察维度分层表头。
- 新增 `VisibleHeaderDimensionPolicy`：按数据实际唯一值自适应区分元数据与可见列头；混合公司、口径、单位或期间不会静默折叠。

## v6.6.x — Financial Statement Context & Canonical Observation Hotfix

- 新增 `DocumentContextResolver`：从文档声明页继承金额单位、币种、报表口径和重述状态；后续显式声明可覆盖，并为每项数值保留 `context_source_page`。
- 修复附注续页将“人民币百万元”误判为“元”的问题；主值保留 PDF 原始计量单位，`value_yuan` 仅作为可审计的派生换算值。
- Canonical Observation Contract 明确拆分 `report_year`、`data_year`、`period_type`、`currency_unit`、`restated_flag` 与 `statement_scope`；宽表列头改为具名维度，避免将 `2023/2022` 混成复合字段。
- 合表观察身份加入来源主表和完整期间/单位/口径维度；每个已解析值保留 PDF、页码、bbox 与上下文来源页的 provenance。
- 仅以中国平安 2023 年报附注 9—12 进行了定向验收；未运行全历史回归。
- 合表 UI 会识别旧版 `merge_canonical_wide.csv`，不再把旧复合列头伪装成 v6.6 Canonical 输出；可在保留来源 Capture 与映射审核的前提下重建派生合表。历史 Capture 若已写错金额单位，仍必须重抓原 PDF，不会被合表静默篡改。

## v6.6.x — Source-Aware Member Table Merge Identity

- 修复实际 Guided Capture 经 `MergeService → table_merge.py` 旧路径时丢失 `member_table` 身份的问题；不再只按 `canonical_item/row_path` 比较不同附注明细表。
- Capture 元数据、作业载荷和合表元数据恢复链统一保存/恢复 `table_family`、`member_table`、`member_table_role`、来源主表、附注号、来源 PDF 和子表顺序。
- `VALUE_CONFLICT` 仅在同表族、同子表、同角色、同行路径、同完整列维度下且金额不同才阻断；来源身份缺失改为可审计 `REVIEW_REQUIRED_SOURCE_IDENTITY`。
- 新增来源身份 QA 输出、合表宽表可见的表族/子表字段、源感知结构顺序和中国平安 2023 真实年报验收。

## v6.6.x — 当前 Capture 质量、审核证据与注册一致性收口

- 修复 `HARD_BOUNDARY_CONFIRMED` 但结果审核显示 `REVIEW_REQUIRED`：当前质量不再继承历史 Job 状态；边界、表头与行语义由 `capture_readiness` 实时合成。
- `raw_item=NULL` 且已认证为 `IMPLICIT_TOTAL` 的空标签合计行视为已恢复结构；只有 `IMPLICIT_ROW_CANDIDATE` 或旧 schema 中未认证的匿名数值行阻断合表。
- 人工边界截断后仅对保留行重新计算 `MIXED` 与隐式行质量，已排除的机器证据仍保留但不再污染当前质量。
- 恢复发现结果审核与 Capture 结构审核的 PDF 预览；支持主表/附注双页、bbox 高亮、PDF页/印刷页，并为缺失、越界、加密和渲染失败提供非崩溃状态。
- 修复并发抓取注册竞争：同步串行化并重试，实时质量回写 `capture_metadata.json`，失败写入 `runtime/registry_sync_errors.jsonl`；CaptureService 在注册缺失时不再把 Job 标成成功。
- 增加 MergeService 实时质量硬门禁；数据库中过期的 `merge_ready` 无法绕过当前机器证据。
- 精化边界：只有相邻附注编号的高置信 `NEXT_NOTE_ORDINAL` 可自动成为硬边界；非相邻同级标题保持中置信待审，含多个数值的普通数据行不会被识别为附注边界。
- 中国平安 2023—2025 三份真实 PDF 完成 12 个明细首次抓取和 12 个认证重跑，全部 `SUCCESS`，并验证当前质量投影、注册持久化与合表门禁。

## v6.5.1 — 多 PDF Anchor 批量计划与 Streamlit 状态修复

- 引导式抓取的 Anchor 从单选改为多选；每份 PDF 保留独立的 `StatementOccurrence`、Anchor Adjudication 和 Capture Plan。
- 批量认证只是一键操作：仍逐份写入审计记录，避免把 2023–2025 年报混成一个跨文档 Anchor。
- 一次认证多份报告后生成多张独立计划；每份计划均为 `1 个主报表构成 + N 个附注明细`，一键抓取也按各自来源 PDF 提交。
- 修复 Streamlit widget key 冲突：按钮 key 不再与 session-state 计划对象共用 `v65_plan`，避免 `StreamlitAPIException`。
- 新增中国平安 2023–2025 真实年报回归：三份合并资产负债表均定位到金融投资 Anchor，每份生成 5 表计划，合计 15 表。

## v6.5 — Statement-Anchored Table Family

- 新增独立 release 目录策略；v6.4 源码快照冻结，DATA_HOME 保持共享、迁移只追加。
- 公司筛选从文件存储名剥离 SHA 前缀，按规范化公司名聚合。
- 新增 `StatementOccurrence`、Anchor Arbitration、Statement Anchor Table、Capture Plan 和引导式一键抓取服务。
- 新增列头附注 section + 行编号组合、附注状态、候选/确认页和 PDF/印刷页双页码合同。
- Discovery 证据先聚类，再审核；新增批量审核与逐条审计写入。
- 继续保留手工/高级抓取入口，避免与引导式主流程混用。

## v6.4 — Generic Discovery Review + Certified Knowledge

### 新增
- 任意 `display_name` 进入 Generic Statement-Guided Family Discovery；preset 改为可选知识包，不再是功能开关。
- 新增不可变机器发现、人工审核、认证发现、快速路径及训练样本的分层 SQLite 证据链。
- 新增审核中心和发现规则与学习库；审核支持 ACCEPTED/REJECTED/OVERRIDDEN/UNRESOLVED，并保留操作者、理由、旧值和新值。
- 新增 company → filing type → statement type → table family → member table 的分层回退契约。
- 公司选择器按规范化公司聚合，避免 asset hash + 公司名重复显示。
- 新增 `version.py` 作为运行时版本单一来源；BAT、launcher、页面统一读取 v6.4。

### 迁移与兼容
- SQLite schema 从 2 增量迁移到 3，仅新增 discovery/adjudication/certified/training 表；不改写既有 PDF、Capture、Merge、Notes 或机器证据。
- v6.3 Family Merge 身份合同继续使用 `table_family/member_table/source_table_title/note_reference`，研究宽表仍隐藏内部 `canonical_key/order_source`。

## v6.3 — Statement-Guided Navigation + Family Merge

### 新增
- 增加 PDF Selection Workspace v2：来源模式、公司/年份多选、文件名包含/排除、筛选结果全选和持久化选择集合。
- 增加可缓存、文本优先的 PDF Index、主报表定位、附注引用抽取、主表—附注导航图与保守回退路径。
- 增加表族三级身份和双轴 Family Merge：成员表保持并列结构，相同列维度合并，行路径含 member table 语义。
- 增加 Research Output Contract v2 和 `column_dimensions` 映射；最终宽表默认隐藏 `canonical_key`、`order_source`。
- 增加独立 Table Notes / Footnote Evidence Layer，原始备注、页码、bbox、来源链与辅助分类可审计保存。

### 兼容与迁移
- **非破坏性 schema 迁移**：SQLite 从 v1 升至 v2，仅新增 `capture_semantics`、`statement_note_edges`、`table_notes`；原 Capture、PDF、JSON、CSV/Parquet 不被回写或重写。
- 旧的单表 Merge 保持可用。Family Merge 是新的派生研究层；完全相同观测键但不同数值仍是阻断性 `VALUE_CONFLICT`。
- FastAPI/React 不属于 v6.3；本版仅固定 API-ready 的结构化数据合同。

## v6.2 — Multi-PDF Table Family + Financial Structure Resolver

### 批量任务与表族
- 增加受控并发的多 PDF 整表抓取、持久化 Job 状态、失败隔离与 retry lineage。
- 增加 `TableFamily`：同一年度可独立抓取多个目标表，并判定 LEGACY_COMBINED / SPLIT_COMPONENTS / PARTIAL_COMPONENTS_REVIEW_REQUIRED 等结构版本。
- 每个批次保留 job manifest 和 schema variant summary，不拼接、不覆盖来源 Capture。

### 财务结构与合表安全
- 增加多证据行结构派生：显式 parent_section、row_level、顺序和小计/合计语义共同形成置信度；缩进/层级不是唯一规则。
- 导出 `row_path`、`parent_row_order`、`structure_confidence`、`structure_evidence`，防止不同父节点下的同名明细相互覆盖。
- 增加单位/四舍五入敏感的小计核对：`PASS` / `PASS_WITH_ROUNDING` / `WARNING`。
- 维度缺失 + 多物理列造成的多值结果改为 `REVIEW_REQUIRED_DIMENSION_AMBIGUITY` 警告；完全同键的不同数值仍为 `VALUE_CONFLICT` 阻断。

### 模板与 LLM 配置
- 增加历史结构模板存储、相似度检索和可替换 `StructurePredictor` 接口，为后续 ML 排序模型预留契约。
- 增加 `config/llm_config.example.yaml` 与本地加载器；本地密钥文件被 `.gitignore` 和交付打包排除。

## v6.1 — Backend Decoupling + SQLite Metadata Registry

### Backend architecture
- Added SQLite metadata control plane at `DATA_HOME/metadata.db`.
- Added `MetadataRegistry` with WAL mode, foreign keys, indexed Capture/Batch/Merge/Job tables.
- Added Repository Layer for Captures, Batches, Merges, PDFs, and Jobs.
- Added Service Layer for Capture, Review, Asset, Batch, Merge, PDF, Registry, and Jobs.
- Added `backend_context.py` dependency container with no Streamlit dependency.
- Added headless `service_cli.py`.

### Metadata registry
- First v6.1 launch bootstraps existing DATA_HOME into SQLite once.
- Registry is rebuildable from filesystem evidence.
- New Capture/review/merge write paths include best-effort registry synchronization hooks.
- Added manual full-sync from UI and CLI.

### Data Asset Management
- Capture asset list now uses SQL-backed filtering and pagination.
- Dependency impact uses indexed `merge_sources` rather than rescanning every Merge for each selection.
- Batch main list excludes fully trashed batches.
- Added Batch aggregate status and dedicated Batch Trash view.
- Lifecycle operations use Service Layer and dual-write to legacy metadata/evidence + SQLite index.

### Job foundation
- Added persistent jobs table and `JobService`.
- Status contract: `QUEUED / RUNNING / SUCCESS / REVIEW_REQUIRED / FAILED / CANCELLED`.
- Heavy multi-PDF worker orchestration remains scheduled for the next workflow release.

### Project cleanup
- Historical per-version README/CHANGELOG files moved from project root to `docs/history/<version>/`.
- Root now uses consolidated `README.md` + `CHANGELOG.md`.
- Current guides live in `docs/current/`.

### Preserved
- v5.7 relative-period/wrapped-row fixes.
- v5.8 absolute-year resolution.
- v5.9 Classic + Generalized dual-header arbitration and topology review.
- v6.0 asset lifecycle, batch invalidation, stale Merge protection, and single-instance launcher.
- v6.0.1 Batch ID callback hotfix.

## v6.0.1
- Fixed Streamlit Session State exception when generating a new Capture Batch ID.

## v6.0
- Added Data Asset Management Center.
- Added Capture lifecycle: ACTIVE / INVALIDATED / TRASHED.
- Added bulk invalidation, trash/restore, batch rerun, Merge dependency stale marking.
- Added single-instance launcher and graceful restart/exit control.

## v5.9
- Added Classic + v5.7 Generalized dual-header parsers.
- Added independent numeric-column referee and parser arbitration.
- Fixed 4-real-column → 8-machine-column header regression.
- Added manual parser selection and safe KEEP/DROP topology review.

Older detailed notes are archived under `docs/history/`.
# v6.2

- 新增 Multi-PDF Parallel Capture、Table Family Capture 与持久化 Batch Job 监控；
- 新增受控 Worker、失败隔离、可重试 FAILED 作业及批次审计汇总；
- 保持 v5.9 / v6.0 / v6.1 回归门槛，并新增 `regression_v62.py`。
# v6.10 — Statement-Scope-First Hierarchical Child Table Discovery

- Hotfix：单选 `CONSOLIDATED` 或 `PARENT_COMPANY` 时，未能可靠推断的
  `UNKNOWN` occurrence 不再生成额外审核 lane；每份 PDF 只显示所选 scope
  的一个 Anchor 选择组。
- Hotfix：人工认证 `UNKNOWN` 机器候选时，`chosen_scope` 作为 Certified
  Scope 单独物化，保留原 `machine_scope`，下游不再将 `UNKNOWN` 传给子表
 发现服务并触发 `SCOPE_LANE_REQUIRED`。
- 新增 `StatementScopeSelection`，默认合并口径，支持母公司及 BOTH 双独立 lane。
- 新增 `AnchorChildConcept`、正式财务附注标题索引、严格 Tier 1→Tier 2→Tier 3 子表召回与早停审计。
- 新增 Thin Candidate、外置 Candidate Evidence、Top-K 局部增强、金额关系验证和可解释全局分配。
- 新增 `CertifiedChildTableLink`，只有认证链接可进入 Capture Orchestrator。
- 在统一资产工作区加入“子表映射”，并将歧义候选送入审核收件箱。
- 修复显式附注编号的子串误匹配；`附注八-10` 不再同时误命中编号 `1`。
- 修复全为 `IMPLICIT_TOTAL` / `DERIVED_TOTAL` 时末列 token 检查误报 `REVIEW_REQUIRED`；现为 `NOT_APPLICABLE`。
- v6.10 为独立 release，v6.9 保持冻结；共享 DATA_HOME 使用 additive schema 12。
