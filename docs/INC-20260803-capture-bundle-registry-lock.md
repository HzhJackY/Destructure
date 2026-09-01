# Capture Bundle 注册锁修复

## 事件

派生子表在 Bundle/Block SQLite 图事务尚未提交时执行 `sync_capture_run`，该同步会以另一连接写入同一 `metadata.db`，形成同进程写锁重入并触发 `database is locked`。

## 修复

先准备子 Capture 的不可变元数据；单个事务只落库 Container、Bundle、Block 及 Bundle-Child 关系；事务退出后再依次同步派生 Capture。子同步失败现在会明确失败并保留审计元数据，不能再作为“成功但不完整”的 Capture 返回。

## 数据边界

不修改已有 Capture 的原始表格、认证结论或生产 DATA_HOME。
