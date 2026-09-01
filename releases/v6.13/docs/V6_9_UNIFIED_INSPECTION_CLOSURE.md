# v6.9 统一逻辑资产检查与审核中心

## 产品边界

`逻辑资产工作区` 是唯一单资产详情实现。它以 `logical_asset_id + capture_version_id + optional table_block_id` 为稳定路由身份，统一承载概览、PDF 证据、附注容器与表块、表头拓扑、行结构、Canonical 数据、勾稽质量、审核、版本比较和下游使用情况。

`审核收件箱` 只负责队列、筛选、批量安全动作和路由，不再复制 PDF 预览或单资产详情。旧 `compound_inspection_ui` 仅保留为兼容跳转；合表的阻断来源和已选来源均进入同一工作区。

## 状态与事务

所有确认、覆盖确认、驳回和未解决操作经 `ReviewService.adjudicate_capture` 进入同一个 Repository 事务。事务同时更新：

- Capture Version 的审核、质量、current 与生命周期状态；
- Review Inbox；
- 版本级 `capture_review_records`；
- Bundle 聚合状态；
- 已依赖该 Capture 的合表失效标记。

提交后由 Merge Eligibility Service 重新读取状态，防止 UI 展示与数据库资格漂移。

## 不可变版本

结构修改不覆盖机器 Capture。`CaptureVersionService.create_structure_revision` 复制证据资产并写入独立人工修订载荷，创建新的 `REVIEW_REQUIRED` 版本。旧版本保持可追溯；新版本经认证后成为 current，旧 current 转为 `SUPERSEDED`。

多表 Bundle 中，每个活跃子表独立审核。Bundle 状态由非 `SUPERSEDED` 子项聚合：

- 全部通过：`READY`
- 部分通过：`PARTIALLY_REVIEW_REQUIRED`
- 无子项通过：`REVIEW_REQUIRED`

## 证据与 UI 所有权

- PDF 证据：`components/pdf_evidence_panel.py`
- 单资产详情：`components/capture_inspection_panel.py`
- 人工动作：`components/review_action_panel.py`
- Bundle/子表：`components/compound_container_panel.py`
- 跨页面路由：`inspection_route.py`

上述 UI 不直接执行 SQL。历史页面只允许调用服务或路由，不得再次形成第二套详情和审核状态机。

## 已知边界

- 已认证版本只读；修改必须创建新版本。
- 历史未注册目录不会作为活动合表来源；需先通过安全索引同步建立逻辑资产身份。
- Streamlit 只能模拟 master-detail 页面切换，路由仍依赖 session state；按钮采用回调写入状态，避免控件实例化后的非法修改。
- 本次只执行 v6.9 定向事务与 UI 合同测试，没有运行全历史回归。

## 旧入口审计

| 模块/入口 | 最终分类 | 生产行为 |
|---|---|---|
| `asset_workspace_ui.py` | CANONICAL_COMPONENT | 唯一 master-detail 资产工作区 |
| `components/capture_inspection_panel.py` | CANONICAL_COMPONENT | 唯一单 Capture 详情实现 |
| `review_inbox_ui.py` | CANONICAL_COMPONENT | 队列、筛选、批量安全动作、路由 |
| `compound_inspection_ui.py` | THIN_REDIRECT / DEPRECATED | 仅跳转逻辑资产工作区 |
| `guided_workflow_ui.py` 的边界/表头审核入口 | THIN_REDIRECT | 仅构造 InspectionRoute |
| `app.py` 旧“人工复核”分支 | DEPRECATED | 非导航可达，立即重定向并停止旧逻辑 |
| 合表来源检查 | CANONICAL_COMPONENT ROUTE | 直接路由 CaptureInspectionPanel |
| 历史底层边界/表头裁决函数 | INTERNAL_ENGINE | 不再由生产 UI 直接调用 |

## 运行调用链

`Review Inbox → InspectionRoute → Logical Asset Workspace → CaptureInspectionPanel → ReviewService → AssetLifecycle/Repository transaction → MergeEligibilityService`
