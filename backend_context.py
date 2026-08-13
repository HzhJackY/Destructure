#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dependency container for v6.1 backend services.

Neither Streamlit nor FastAPI is imported here. The same service graph can be
used by CLI, tests, future FastAPI, and the transitional Streamlit UI.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from metadata_registry import MetadataRegistry
from registry_sync import RegistrySynchronizer
from repositories import CaptureRepository,BatchRepository,MergeRepository,PdfRepository,JobRepository,AssetGovernanceRepository
from services import (
    AssetService,BatchService,MergeService,PdfService,JobService,CaptureService,
    CaptureCompletionService,
    ReviewService,RegistryService,DiscoveryService,GuidedCaptureService,
    ChildCaptureExecutionService,
    ResearchBatchService,LogicalAssetService,AssetLifecycleService,
    ReviewInboxService,AssetQueryService,ArchiveService,MergeEligibilityService,
    CaptureVersionService,ReviewTaskService,
)
from jobs.table_capture_runner import TableCaptureRunner
from discovery_registry import DiscoveryRegistry
from research_definition_registry import ResearchDefinitionService
from generic_discovery_engine import GenericDiscoveryService
from discovery_strategies import (
    StrategyRegistry,CertifiedTargetStrategy,ManualCertifiedRoiStrategy,DirectQueryStrategy,
    RegistryDiscoveryStrategy,
)
from capture_orchestrator import CaptureOrchestrator
from version import APP_VERSION
from v69_learning import seed_label_schemas
from hierarchical_child_discovery import (
    ChildDiscoveryRepository,FinancialNoteIndexService,
    HierarchicalChildTableDiscoveryService,
)


@dataclass
class BackendServices:
    registry: MetadataRegistry
    synchronizer: RegistrySynchronizer
    capture_repository: CaptureRepository
    batch_repository: BatchRepository
    merge_repository: MergeRepository
    pdf_repository: PdfRepository
    job_repository: JobRepository
    asset_service: AssetService
    batch_service: BatchService
    merge_service: MergeService
    pdf_service: PdfService
    job_service: JobService
    capture_service: CaptureService
    review_service: ReviewService
    registry_service: RegistryService
    table_capture_runner: TableCaptureRunner
    discovery_registry: DiscoveryRegistry
    discovery_service: DiscoveryService
    guided_capture_service: GuidedCaptureService
    research_batch_service: ResearchBatchService
    research_definition_service: ResearchDefinitionService
    generic_discovery_service: GenericDiscoveryService
    asset_governance_repository: AssetGovernanceRepository
    logical_asset_service: LogicalAssetService
    asset_lifecycle_service: AssetLifecycleService
    review_inbox_service: ReviewInboxService
    asset_query_service: AssetQueryService
    archive_service: ArchiveService
    merge_eligibility_service: MergeEligibilityService
    capture_completion_service: CaptureCompletionService
    capture_orchestrator: CaptureOrchestrator
    capture_version_service: CaptureVersionService
    review_task_service: ReviewTaskService
    child_discovery_repository: ChildDiscoveryRepository
    financial_note_index_service: FinancialNoteIndexService
    hierarchical_child_discovery_service: HierarchicalChildTableDiscoveryService
    child_capture_execution_service: ChildCaptureExecutionService


def build_backend_services(paths: dict[str, Path]) -> BackendServices:
    registry=MetadataRegistry(paths['metadata_db'])
    # Additive, idempotent v6.9 learning-contract bootstrap.  It stores only
    # label schemas; no historic values are inferred or rewritten.
    seed_label_schemas(registry)
    synchronizer=RegistrySynchronizer(registry,paths)
    capture_repo=CaptureRepository(registry);batch_repo=BatchRepository(registry);merge_repo=MergeRepository(registry);pdf_repo=PdfRepository(registry);job_repo=JobRepository(registry)
    asset=AssetService(registry,capture_repo,synchronizer,paths)
    batch=BatchService(batch_repo,asset)
    governance_repo=AssetGovernanceRepository(registry)
    logical_assets=LogicalAssetService(governance_repo,APP_VERSION)
    lifecycle=AssetLifecycleService(governance_repo,APP_VERSION)
    review_inbox=ReviewInboxService(governance_repo)
    asset_query=AssetQueryService(governance_repo)
    archive=ArchiveService(governance_repo)
    merge_eligibility=MergeEligibilityService(asset_query)
    batch.configure(merge_eligibility_service=merge_eligibility)
    review_tasks=ReviewTaskService(governance_repo,APP_VERSION)
    capture_completion=CaptureCompletionService(
        governance_repository=governance_repo,
        review_task_service=review_tasks,
        producer_version=APP_VERSION,
    )
    review=ReviewService(governance_repo,lifecycle,merge_eligibility,review_tasks)
    review_inbox.configure(review)
    capture_versions=CaptureVersionService(governance_repo,capture_repo,review_inbox,paths,APP_VERSION)
    merge=MergeService(merge_repo,capture_repo,registry,synchronizer,paths,eligibility_service=merge_eligibility)
    pdf=PdfService(pdf_repo);job=JobService(job_repo);capture=CaptureService(capture_repo,paths);registry_service=RegistryService(registry,synchronizer,paths)
    discovery=DiscoveryRegistry(registry)
    child_discovery_repo=ChildDiscoveryRepository(registry)
    financial_note_index=FinancialNoteIndexService(child_discovery_repo)
    hierarchical_child_discovery=HierarchicalChildTableDiscoveryService(
        child_discovery_repo,financial_note_index,
    )
    discovery_service=DiscoveryService(discovery, paths['cache'])
    research_batch_service=ResearchBatchService(registry,asset_service=asset)
    research_definition_service=ResearchDefinitionService(registry)
    generic_discovery_service=GenericDiscoveryService(research_definition_service, paths['cache'])
    strategies=StrategyRegistry([
        CertifiedTargetStrategy(),ManualCertifiedRoiStrategy(),DirectQueryStrategy(),
        RegistryDiscoveryStrategy(generic_discovery_service),
    ])
    orchestrator=CaptureOrchestrator(
        repository=governance_repo,strategies=strategies,
        executor=capture._execute_resolved_target,capture_repository=capture_repo,
        logical_asset_service=logical_assets,lifecycle_service=lifecycle,
        review_inbox_service=review_inbox,
        completion_service=capture_completion,
    )
    runner=TableCaptureRunner(job_service=job,capture_service=capture,audit_dir=paths['table_captures'])
    capture.configure(orchestrator=orchestrator,runner=runner)
    asset.configure(capture_service=capture,governance_repository=governance_repo)
    # Existing-Capture projection is an explicit migration/reassessment
    # operation. Backend construction and Streamlit reruns are read-only.
    guided_capture_service=GuidedCaptureService(registry=registry,capture_service=capture,audit_dir=paths['table_captures'])
    child_capture_execution_service=ChildCaptureExecutionService(
        registry=registry,
        capture_service=capture,
        table_capture_runner=runner,
        research_batch_service=research_batch_service,
        guided_capture_service=guided_capture_service,
        capture_version_service=capture_versions,
        hierarchical_child_discovery_service=hierarchical_child_discovery,
        capture_orchestrator=orchestrator,
    )
    return BackendServices(
        registry,synchronizer,capture_repo,batch_repo,merge_repo,pdf_repo,job_repo,
        asset,batch,merge,pdf,job,capture,review,registry_service,runner,discovery,
        discovery_service,guided_capture_service,research_batch_service,
        research_definition_service,generic_discovery_service,governance_repo,
        logical_assets,lifecycle,review_inbox,asset_query,archive,merge_eligibility,
        capture_completion,orchestrator,capture_versions,review_tasks,
        child_discovery_repo,financial_note_index,hierarchical_child_discovery,
        child_capture_execution_service,
    )
