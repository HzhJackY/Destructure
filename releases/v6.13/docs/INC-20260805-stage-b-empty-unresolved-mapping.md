# INC-20260805 — Stage B 空壳 unresolved 映射误挡正常抓取

## 现象

中国平安的 Stage B 路径中，部分 `v610_child_mappings` 进入“阶段 B：校正未决候选语义”页，但对应 `unresolved_inventory_cases()` 为空。页面仍展示“没有 OPEN/UNRESOLVED inventory case”警告，导致正常抓取路径被异常页遮住。

## 根因

系统把“存在历史 mapping”误当成“当前仍有可人工校正的 unresolved case”。空壳映射队列没有被清理，Stage B 因而被错误导向人工校正界面。

## 修复

仅当 mappings 中真实存在 OPEN/UNRESOLVED case 时才渲染人工校正页；空壳映射直接清理并返回正常 Stage B Capture Plan 路径，不再阻塞批次。
