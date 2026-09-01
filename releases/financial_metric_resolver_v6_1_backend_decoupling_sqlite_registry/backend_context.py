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
from repositories import CaptureRepository,BatchRepository,MergeRepository,PdfRepository,JobRepository
from services import AssetService,BatchService,MergeService,PdfService,JobService,CaptureService,ReviewService,RegistryService


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


def build_backend_services(paths: dict[str, Path]) -> BackendServices:
    registry=MetadataRegistry(paths['metadata_db'])
    synchronizer=RegistrySynchronizer(registry,paths)
    capture_repo=CaptureRepository(registry);batch_repo=BatchRepository(registry);merge_repo=MergeRepository(registry);pdf_repo=PdfRepository(registry);job_repo=JobRepository(registry)
    asset=AssetService(registry,capture_repo,synchronizer,paths)
    batch=BatchService(batch_repo,asset)
    merge=MergeService(merge_repo,capture_repo,registry,synchronizer,paths)
    pdf=PdfService(pdf_repo);job=JobService(job_repo);capture=CaptureService(capture_repo,paths);review=ReviewService();registry_service=RegistryService(registry,synchronizer,paths)
    return BackendServices(registry,synchronizer,capture_repo,batch_repo,merge_repo,pdf_repo,job_repo,asset,batch,merge,pdf,job,capture,review,registry_service)
