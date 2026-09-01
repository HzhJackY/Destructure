from __future__ import annotations
from pathlib import Path
from typing import Any
from registry_bridge import sync_capture_run


class ReviewService:
    """Headless adjudication façade around deterministic review engines."""
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
