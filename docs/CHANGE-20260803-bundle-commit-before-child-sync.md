# 变更：Bundle/Block 先提交，再同步子 Capture

`CaptureService._create_legacy` 的注册顺序已调整为：

1. 生成主/子 Capture 的物理机器证据和子 Capture 元数据；
2. 事务内写入 Note Container、Capture Bundle、Table Block、Bundle-Child 图；
3. 事务提交后，才对每个派生子 Capture 调用 Registry 同步；
4. 子同步任一失败即以明确错误结束请求，并在主 Capture 元数据中留下失败状态与明细。

此变更防止同一 SQLite 数据库在未提交的 Bundle 写事务中被第二连接重入写入。
