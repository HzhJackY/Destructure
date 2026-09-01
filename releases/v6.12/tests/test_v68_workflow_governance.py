from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from capture_models import CaptureMode, CaptureRequest
from capture_orchestrator import CaptureOrchestrator
from discovery_strategies import CertifiedTargetStrategy, StrategyRegistry
from jobs.table_capture_runner import TableCaptureRunner
from metadata_registry import MetadataRegistry
from repositories.asset_governance_repository import AssetGovernanceRepository
from services.asset_governance_services import (
    ArchiveService, AssetLifecycleService, AssetQueryService,
    LogicalAssetService, MergeEligibilityService, ReviewInboxService,
)
from services.review_service import ReviewService
from services.review_task_service import ReviewTaskService


READY_EVIDENCE = {
    "boundary_status": "HARD_BOUNDARY_CONFIRMED",
    "header_dimension_status": "AUTO_CONFIRMED",
    "unit": "万元",
    "rows": [], "stats": {},
}
REVIEW_EVIDENCE = {
    "boundary_status": "REVIEW_REQUIRED",
    "header_dimension_status": "AUTO_CONFIRMED",
    "unit": "万元",
    "rows": [], "stats": {},
}


class PhysicalRepo:
    def __init__(self):
        self.rows = {}

    def get(self, capture_id):
        return self.rows.get(capture_id)


class FakeJobService:
    def __init__(self):
        self.jobs = []

    def create(self, job_type, *, batch_id, payload):
        row = {"job_id": f"JOB_{len(self.jobs)+1}", "job_type": job_type,
               "batch_id": batch_id, "payload": payload, "status": "QUEUED",
               "progress": 0.0}
        self.jobs.append(row)
        return dict(row)

    def list(self, *, batch_id, status=None, limit=100000):
        return [dict(row) for row in self.jobs
                if row["batch_id"] == batch_id and (status is None or row["status"] == status)]

    def update(self, job_id, status=None, progress=None, target_asset_id=None, result=None, error=None):
        row = next(x for x in self.jobs if x["job_id"] == job_id)
        if error is not None:
            row["status"] = "FAILED"; row["error"] = str(error)
        if status is not None: row["status"] = status
        if progress is not None: row["progress"] = progress
        if target_asset_id is not None: row["target_asset_id"] = target_asset_id
        if result is not None: row["result"] = result


class V68WorkflowGovernanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = MetadataRegistry(Path(self.tmp.name) / "metadata.db")
        self.governance = AssetGovernanceRepository(self.registry)
        self.physical = PhysicalRepo()
        self.logical = LogicalAssetService(self.governance, "v6.8")
        self.lifecycle = AssetLifecycleService(self.governance, "v6.8")
        self.review_service = ReviewService(self.governance)
        self.inbox = ReviewInboxService(self.governance, review_service=self.review_service)
        self.counter = 0
        self.evidence = READY_EVIDENCE

        def executor(request, target):
            self.counter += 1
            capture_id = f"CAP_{self.counter}"
            self.physical.rows[capture_id] = {"capture_id": capture_id}
            return {"capture_id": capture_id, "metadata": {
                "company": "中国平安", "document_year": "2023",
                "table_family": "金融投资", "member_table": request.member_table_id,
            }, "result": dict(self.evidence)}

        self.orchestrator = CaptureOrchestrator(
            repository=self.governance,
            strategies=StrategyRegistry([CertifiedTargetStrategy()]),
            executor=executor, capture_repository=self.physical,
            logical_asset_service=self.logical, lifecycle_service=self.lifecycle,
            review_inbox_service=self.inbox,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, member_table_id="债权投资"):
        return CaptureRequest.new(
            capture_mode=CaptureMode.CERTIFIED_TARGET,
            source_pdf_path="C:/test.pdf", table_family_id="金融投资",
            member_table_id=member_table_id,
            research_task_id="TASK_1",
            research_definition_id="FINANCIAL_INVESTMENT_V1",
            definition_version="1.0",
            request_metadata={
                "company": "中国平安", "report_year": "2023",
                "certified_target": {
                    "confirmed_note_pdf_page_index": 10,
                    "target_heading": "债权投资",
                    "status": "CERTIFIED_NOTE_TARGET", "confidence": 1.0,
                    "statement_scope": "CONSOLIDATED",
                },
            },
        )

    def test_unified_orchestrator_versions_review_archive(self):
        first = self.orchestrator.execute(self.request())
        self.assertEqual(first["status"], "SUCCESS")
        self.assertTrue(first["registration_confirmed"])
        query = AssetQueryService(self.governance)
        eligible = query.merge_eligible()
        self.assertEqual([x["capture_id"] for x in eligible], ["CAP_1"])
        with self.registry.connect() as conn:
            conn.execute(
                """INSERT INTO merge_projects(merge_id,run_path,dependency_status,updated_at)
                   VALUES('M1','C:/merge','CURRENT',datetime('now'))"""
            )
            conn.execute("INSERT INTO merge_sources(merge_id,capture_id) VALUES('M1','CAP_1')")

        self.evidence = REVIEW_EVIDENCE
        second = self.orchestrator.execute(self.request())
        self.assertEqual(second["status"], "REVIEW_REQUIRED")
        rows = query.search(include_archived=True)
        current = [x for x in rows if x["is_current"]]
        self.assertEqual(current[0]["capture_id"], "CAP_2")
        self.assertEqual(len(self.inbox.list(status="PENDING")), 1)
        view_id = self.inbox.save_view("结构待审核", {"status": "PENDING"})
        self.assertEqual(self.inbox.list_views()[0]["view_id"], view_id)

        self.inbox.resolve("CAP_2", "CONFIRMED")
        self.assertEqual(self.inbox.list(), [])
        self.assertEqual(query.get_current_capture(first["logical_asset_id"])["capture_id"], "CAP_2")
        versions = query.get_capture_versions(first["logical_asset_id"])
        self.assertEqual(next(x for x in versions if x["capture_id"] == "CAP_1")["asset_status"], "SUPERSEDED")
        with self.registry.connect() as conn:
            stale = conn.execute("SELECT dependency_status FROM merge_projects WHERE merge_id='M1'").fetchone()[0]
        self.assertEqual(stale, "STALE_NEW_CURRENT_VERSION_AVAILABLE")

        asset_id = first["logical_asset_id"]
        archive = ArchiveService(self.governance)
        archive.archive([asset_id], reason="TEST")
        self.assertEqual(query.merge_eligible(), [])
        archive.restore([asset_id], reason="TEST")
        self.assertEqual([x["capture_id"] for x in query.merge_eligible()], ["CAP_2"])
        MergeEligibilityService(query).assert_capture_ids(["CAP_2"])
        archive.archive_versions(["CAP_2"], reason="TEST_VERSION")
        self.assertEqual(query.merge_eligible(), [])
        archive.restore_versions(["CAP_2"], reason="TEST_VERSION")
        self.assertEqual([x["capture_id"] for x in query.merge_eligible()], ["CAP_2"])

        archive.archive_parent("RESEARCH_TASK", "TASK_1", reason="TEST_PARENT")
        self.assertEqual(query.merge_eligible(), [])
        archive.restore_parent("RESEARCH_TASK", "TASK_1", reason="TEST_PARENT")
        self.assertEqual([x["capture_id"] for x in query.merge_eligible()], ["CAP_2"])

        self.governance.set_capture_lifecycle(["CAP_2"], status="TRASHED", actor="TEST", reason="TEST")
        self.assertEqual(query.merge_eligible(), [])
        self.governance.set_capture_lifecycle(["CAP_2"], status="ACTIVE", actor="TEST", reason="TEST", restore=True)
        self.assertEqual([x["capture_id"] for x in query.merge_eligible()], ["CAP_2"])

        other = self.governance.get_or_create_logical_asset({
            "company": "中国平安", "document_year": "2023", "table_family": "金融投资",
            "member_table": "其他债权投资", "member_table_role": "NOTE_DETAIL",
        })
        self.assertNotEqual(other["logical_asset_id"], asset_id)
        with self.registry.connect() as conn:
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM asset_status_transitions").fetchone()[0], 0)

    def test_runner_explicit_join(self):
        jobs = FakeJobService()

        class Capture:
            def execute_queued_request(_, request):
                time.sleep(.01)
                return {"status": "SUCCESS", "capture_id": "CAP_RUN",
                        "logical_asset_id": "LASSET_RUN", "registration_confirmed": True}

        runner = TableCaptureRunner(
            job_service=jobs, capture_service=Capture(), audit_dir=Path(self.tmp.name)
        )
        created = runner.enqueue_requests([self.request()], batch_id="BATCH")
        self.assertEqual(len(created), 1)
        runner.start(batch_id="BATCH", max_workers=1)
        monitor = runner.join("BATCH", timeout=5)
        self.assertTrue(monitor["joined"])
        self.assertEqual(monitor["counts"]["SUCCESS"], 1)
        runner.shutdown(wait=True)

    def test_faceted_query_pagination_and_safe_bulk_review(self):
        self.evidence = REVIEW_EVIDENCE
        first = self.orchestrator.execute(self.request())
        second_request = self.request("其他债权投资")
        second = self.orchestrator.execute(second_request)
        query = AssetQueryService(self.governance)
        found = query.search(
            filters={"company_id": "中国平安", "quality_status": "REVIEW_REQUIRED"},
            search="债权", pagination={"page": 1, "page_size": 1},
            sort={"field": "member_table_id", "direction": "ASC"},
        )
        self.assertEqual(len(found), 1)
        pending = self.inbox.list(status="PENDING", company_id="中国平安", page_size=20)
        self.assertEqual(len(pending), 2)
        capture_ids = [first["capture_id"], second["capture_id"]]
        self.assertTrue(self.inbox.validate_bulk_action(capture_ids, "CONFIRMED")["allowed"])
        self.assertEqual(self.inbox.bulk_resolve(capture_ids, "CONFIRMED"), 2)
        self.assertEqual(self.inbox.list(), [])

    def test_bulk_confirm_rejects_heterogeneous_or_conflicting_selection(self):
        self.evidence = REVIEW_EVIDENCE
        first = self.orchestrator.execute(self.request())
        second_request = self.request("其他债权投资")
        second = self.orchestrator.execute(second_request)
        with self.registry.connect() as conn:
            conn.execute(
                "UPDATE review_queue SET primary_review_reason='SOURCE_IDENTITY_MISSING' WHERE capture_id=?",
                (second["capture_id"],),
            )
        decision = self.inbox.validate_bulk_action(
            [first["capture_id"], second["capture_id"]], "CONFIRMED"
        )
        self.assertFalse(decision["allowed"])
        with self.assertRaises(ValueError):
            self.inbox.bulk_resolve(
                [first["capture_id"], second["capture_id"]], "CONFIRMED"
            )
        self.assertEqual(
            self.inbox.bulk_resolve(
                [first["capture_id"], second["capture_id"]], "REJECTED"
            ),
            2,
        )
        self.assertEqual(AssetQueryService(self.governance).merge_eligible(), [])

    def test_failed_rerun_preserves_old_current(self):
        first = self.orchestrator.execute(self.request())
        old_executor = self.orchestrator.executor
        self.orchestrator.executor = lambda request, target: (_ for _ in ()).throw(
            RuntimeError("SIMULATED_CAPTURE_FAILURE")
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "SIMULATED_CAPTURE_FAILURE"):
                self.orchestrator.execute(self.request())
        finally:
            self.orchestrator.executor = old_executor
        current = AssetQueryService(self.governance).get_current_capture(
            first["logical_asset_id"]
        )
        self.assertEqual(current["capture_id"], first["capture_id"])
        with self.registry.connect() as conn:
            failed = conn.execute(
                "SELECT status FROM capture_requests ORDER BY requested_at DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(failed["status"], "FAILED")

    def test_static_production_path_and_release_contract(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "app.py").read_text(encoding="utf-8")
        generic = (root / "generic_discovery_engine.py").read_text(encoding="utf-8")
        guided_ui = (root / "guided_workflow_ui.py").read_text(encoding="utf-8")
        self.assertNotIn("capture_named_table(", app)
        self.assertNotIn('PRESETS["__v67_runtime__"]', generic)
        self.assertNotIn("generic_discovery\").PRESETS", guided_ui)
        self.assertIn("family_discovery_context", guided_ui)
        self.assertIn("daemon=False", (root / "jobs/table_capture_runner.py").read_text(encoding="utf-8"))
        self.assertIn('APP_VERSION = "v6.11"', (root / "version.py").read_text(encoding="utf-8"))
        self.assertIn('APP_VERSION = "v6.7"', (root.parent / "v6.7/version.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
