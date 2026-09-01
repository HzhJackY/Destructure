# Architecture Delta — v6.13 Registry Governance

新增 owner 只位于既有 `ResearchDefinitionService` 与 `ChildDiscoveryRepository`：

```text
ResearchDefinitionService
  ├─ built-in Registry seed / read-only guard
  ├─ DATA_HOME user_registry_drafts
  └─ validate + atomic activation to existing ACTIVE registry tables

GenericDiscoveryService
  └─ DIRECT_MAIN_STATEMENT_TABLE (native index only)

ChildDiscoveryRepository
  └─ direct primary-statement CertifiedChildTableLink + certified segment
```

这不是新流水线。直接主表策略仍输出标准 occurrence，仍由 Anchor 审核触发标准
CertifiedChildTableLink，再由既有 CaptureRequest、CaptureDecisionReducer、Canonical、
Merge 和 Research XLSX 消费。
