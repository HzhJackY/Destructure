"""Persistent v6.8 runner with explicit join/shutdown semantics."""
from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

from capture_models import CaptureMode, CaptureRequest
from services.table_family_service import TableFamily, detect_schema_variant

TERMINAL = {"SUCCESS", "REVIEW_REQUIRED", "FAILED", "CANCELLED", "SKIPPED"}
NOT_FOUND_MARKERS = ("未找到", "not found", "no table", "table title")


class TableCaptureRunner:
    def __init__(self, *, job_service, capture_service, audit_dir: Path):
        self.job_service = job_service
        self.capture_service = capture_service
        self.audit_dir = Path(audit_dir)
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._closed = False

    def enqueue_requests(
        self, requests: Iterable[CaptureRequest], batch_id: str | None = None
    ) -> list[dict[str, Any]]:
        if self._closed:
            raise RuntimeError("TABLE_CAPTURE_RUNNER_CLOSED")
        batch_id = batch_id or "CAPTURE_" + uuid.uuid4().hex[:12]
        jobs = []
        for request in requests:
            request.validate()
            metadata = dict(request.request_metadata or {})
            payload = {
                "capture_request": request.to_dict(),
                # Read-only compatibility projection for existing monitoring
                # and research-batch review queries. Execution never consumes
                # these duplicated fields.
                "capture_plan_id": metadata.get("capture_plan_id"),
                "plan_member_table": request.member_table_id,
                "capture_query_title": metadata.get("table_query"),
                "pdf_path": request.source_pdf_path,
                "table_query": metadata.get("table_query") or request.member_table_id,
                "target_role": metadata.get("member_table_role"),
                "options": metadata,
                "family": {"display_name": request.table_family_id},
            }
            jobs.append(self.job_service.create("TABLE_CAPTURE", batch_id=batch_id, payload=payload))
        self._write_manifest(batch_id, None, jobs)
        return jobs

    def enqueue(
        self, *, pdf_paths: Iterable[Path], family: TableFamily,
        batch_id: str, options: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Compatibility adapter for old callers; emits CaptureRequest records."""
        requests = []
        for pdf_path in map(Path, pdf_paths):
            for target in family.targets:
                certified = dict(options.get("certified_note_target") or {})
                page = int(options.get("start_page_override") or 1)
                if not certified:
                    certified = {
                        "confirmed_note_pdf_page_index": page,
                        "target_heading": target.name,
                        "status": "MANUAL_CERTIFIED",
                        "confidence": 1.0,
                    }
                requests.append(CaptureRequest.new(
                    capture_mode=CaptureMode.CERTIFIED_TARGET,
                    source_pdf_path=str(pdf_path.resolve()),
                    table_family_id=family.display_name,
                    member_table_id=str(options.get("member_table") or target.name),
                    request_metadata={
                        **dict(options), "table_query": target.name,
                        "member_table_role": options.get("member_table_role") or target.role,
                        "certified_target": certified, "batch_id": batch_id,
                    },
                ))
        return self.enqueue_requests(requests, batch_id=batch_id)

    def start(self, *, batch_id: str, max_workers: int = 3) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("TABLE_CAPTURE_RUNNER_CLOSED")
            existing = self._threads.get(batch_id)
            if existing and existing.is_alive():
                return
            thread = threading.Thread(
                target=self.run, kwargs={"batch_id": batch_id, "max_workers": max_workers},
                name=f"capture-batch-{batch_id}", daemon=False,
            )
            self._threads[batch_id] = thread
            thread.start()

    def join(self, batch_id: str, timeout: float | None = None) -> dict[str, Any]:
        thread = self._threads.get(batch_id)
        if thread:
            thread.join(timeout)
        monitor = self.monitor(batch_id)
        monitor["joined"] = not bool(thread and thread.is_alive())
        return monitor

    def shutdown(self, wait: bool = True) -> None:
        self._closed = True
        if wait:
            for thread in list(self._threads.values()):
                thread.join()

    close = shutdown

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.shutdown(wait=True)

    def run(self, *, batch_id: str, max_workers: int = 3) -> dict[str, Any]:
        queued = [j for j in self.job_service.list(batch_id=batch_id, limit=100000)
                  if j["status"] == "QUEUED"]
        with ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 8)),
            thread_name_prefix="table-capture",
        ) as pool:
            futures = [pool.submit(self._run_one, job) for job in queued]
            for future in as_completed(futures):
                future.result()
        monitor = self.monitor(batch_id)
        if monitor["complete"] != monitor["total"]:
            raise RuntimeError("BATCH_SUMMARY_BEFORE_ALL_JOBS_TERMINAL")
        self._write_summary(batch_id)
        return monitor

    def retry_failed(self, *, batch_id: str, max_workers: int = 3) -> list[dict]:
        requests = []
        for old in self.job_service.list(batch_id=batch_id, status="FAILED", limit=100000):
            body = dict((old.get("payload") or {}).get("capture_request") or {})
            if not body:
                continue
            previous = CaptureRequest.from_dict(body)
            payload = previous.to_dict()
            payload.update({
                "request_id": "CREQ_" + uuid.uuid4().hex,
                "capture_mode": CaptureMode.FAILED_JOB_RETRY.value,
                "retry_of_request_id": previous.request_id,
            })
            requests.append(CaptureRequest.from_dict(payload))
        jobs = self.enqueue_requests(requests, batch_id=batch_id) if requests else []
        if jobs:
            self.start(batch_id=batch_id, max_workers=max_workers)
        return jobs

    def monitor(self, batch_id: str) -> dict[str, Any]:
        jobs = self.job_service.list(batch_id=batch_id, limit=100000)
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job["status"]] = counts.get(job["status"], 0) + 1
        total = len(jobs)
        complete = sum(counts.get(status, 0) for status in TERMINAL)
        return {
            "batch_id": batch_id, "total": total, "complete": complete,
            "progress": complete / total if total else 1.0, "counts": counts,
            "is_running": bool(counts.get("RUNNING") or counts.get("QUEUED")),
            "jobs": jobs,
        }

    def _run_one(self, job: dict[str, Any]) -> None:
        payload = job.get("payload") or {}
        self.job_service.update(job["job_id"], status="RUNNING", progress=.05)
        try:
            request = CaptureRequest.from_dict(payload["capture_request"])
            result = self.capture_service.execute_queued_request(request)
            status = str(result.get("status") or "FAILED")
            if status not in {"SUCCESS", "REVIEW_REQUIRED"}:
                status = "REVIEW_REQUIRED" if status == "READY" else "FAILED"
            if status == "FAILED":
                raise RuntimeError(str(result.get("reason") or "CAPTURE_REQUEST_FAILED"))
            if result.get("capture_id") and not result.get("registration_confirmed"):
                raise RuntimeError("JOB_SUCCESS_REQUIRES_REGISTRATION_CONFIRMATION")
            self.job_service.update(
                job["job_id"], status=status, progress=1.0,
                target_asset_id=result.get("capture_id"),
                result={
                    "capture_id": result.get("capture_id"),
                    "logical_asset_id": result.get("logical_asset_id"),
                    "request_id": request.request_id,
                    "registration_confirmed": result.get("registration_confirmed", False),
                },
            )
        except Exception as exc:
            if any(marker in str(exc).lower() for marker in NOT_FOUND_MARKERS):
                self.job_service.update(
                    job["job_id"], status="SKIPPED", progress=1.0,
                    result={"reason": "TABLE_NOT_FOUND"},
                )
            else:
                self.job_service.update(job["job_id"], error=exc)

    def _write_manifest(self, batch_id: str, family, jobs: list[dict[str, Any]]) -> None:
        path = self.audit_dir / "batch_jobs"
        path.mkdir(parents=True, exist_ok=True)
        body = {
            "batch_id": batch_id,
            "family": family.to_dict() if family is not None else None,
            "job_ids": [job["job_id"] for job in jobs],
            "request_ids": [
                ((job.get("payload") or {}).get("capture_request") or {}).get("request_id")
                for job in jobs
            ],
        }
        (path / f"{batch_id}.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_summary(self, batch_id: str) -> None:
        monitor = self.monitor(batch_id)
        groups: dict[str, list[dict[str, Any]]] = {}
        for job in monitor["jobs"]:
            request = ((job.get("payload") or {}).get("capture_request") or {})
            groups.setdefault(request.get("source_pdf_path", ""), []).append(job)
        variants = []
        for pdf, jobs in groups.items():
            variants.append({
                "pdf_path": pdf,
                "schema_variant": detect_schema_variant({
                    "role": (((job.get("payload") or {}).get("capture_request") or {})
                             .get("request_metadata") or {}).get("member_table_role"),
                    "status": job["status"],
                } for job in jobs),
            })
        path = self.audit_dir / "batch_jobs" / f"{batch_id}_summary.json"
        path.write_text(
            json.dumps({"monitor": monitor | {"jobs": []},
                        "pdf_schema_variants": variants}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
