from __future__ import annotations
from pathlib import Path
from typing import Any
from registry_bridge import sync_capture_run


class ReviewService:
    """Headless adjudication façade around deterministic review engines."""
    def __init__(self, governance_repository=None, lifecycle_service=None, merge_eligibility_service=None,
                 review_task_service=None):
        self.governance = governance_repository
        self.lifecycle = lifecycle_service
        self.merge_eligibility = merge_eligibility_service
        self.review_tasks = review_task_service

    def _sync(self,run_dir:Path):sync_capture_run(Path(run_dir))
    def apply_boundary(self,run_dir:Path,last_included_row_order:int,reviewer_note:str='')->dict[str,Any]:
        from capture_library import apply_boundary_review
        out=apply_boundary_review(Path(run_dir),int(last_included_row_order),reviewer_note);self._sync(run_dir);return out
    def reset_boundary(self,run_dir:Path)->None:
        from capture_library import reset_boundary_review
        reset_boundary_review(Path(run_dir));self._sync(run_dir)
    def apply_header_dimensions(self,run_dir:Path,edited_columns:list[dict[str,Any]],reviewer_note:str='')->dict[str,Any]:
        from header_review import apply_header_dimension_review
        out=apply_header_dimension_review(Path(run_dir),edited_columns,reviewer_note);self._sync(run_dir);return out
    def reset_header_dimensions(self,run_dir:Path)->dict[str,Any]:
        from header_review import reset_header_dimension_review
        out=reset_header_dimension_review(Path(run_dir));self._sync(run_dir);return out
    def apply_column_topology(self,run_dir:Path,actions:list[dict[str,Any]],reviewer_note:str='')->dict[str,Any]:
        from column_topology_review import apply_column_topology_review
        out=apply_column_topology_review(Path(run_dir),actions,reviewer_note);self._sync(run_dir);return out
    def reset_column_topology(self,run_dir:Path)->dict[str,Any]:
        from column_topology_review import reset_column_topology_review
        out=reset_column_topology_review(Path(run_dir));self._sync(run_dir);return out

    def adjudicate_capture(
        self, *, capture_id: str, action: str, actor: str = "USER",
        reason: str = "", override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """One transactional review path for every production UI."""
        if self.governance is None:
            raise RuntimeError("REVIEW_GOVERNANCE_NOT_CONFIGURED")
        if str(action).upper() in {"CONFIRMED","CONFIRMED_HUMAN","CONFIRMED_AUTO","CONFIRMED_OVERRIDE"}:
            if self.review_tasks is not None:
                self.review_tasks.validate_final_confirm(capture_id)
        result = self.governance.resolve_review(
            capture_id, action, actor=actor, reason=reason, override=override,
        )
        if self.merge_eligibility is not None:
            result["merge_eligible_after_commit"] = any(
                str(row.get("capture_id")) == str(capture_id)
                for row in self.merge_eligibility.eligible_assets()
            )
        return result

    def decide_task(self, *, capture_id: str, task_type: str, decision: str,
                    actor: str = "USER", reason: str = "",
                    evidence: dict[str,Any] | None = None) -> dict[str,Any]:
        if self.review_tasks is None:
            raise RuntimeError("REVIEW_TASK_SERVICE_NOT_CONFIGURED")
        return self.review_tasks.decide_task(
            capture_id,task_type,decision,reviewer=actor,reason=reason,evidence=evidence,
        )
