from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from repositories.pdf_repository import PdfRepository


class PdfService:
    def __init__(self, repo: PdfRepository, paths: dict[str, Path]):
        self.repo = repo
        self.registry = repo.registry
        self.upload_root = Path(paths["uploads"]).resolve()
        self.trash_root = Path(paths["pdf_trash"]).resolve()
        self.cache_root = Path(paths["cache"]).resolve()
        self.text_index_root = Path(paths["text_indexes"]).resolve()
        self.trash_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def _safe_source(self, value: Any, *, expected_root: Path) -> Path:
        path = Path(str(value or "")).resolve()
        if not self._inside(path, expected_root) or not path.is_file():
            raise PermissionError(f"PDF_PATH_OUTSIDE_MANAGED_ROOT:{path}")
        return path

    def list(
        self, *, limit: int = 5000, include_trash: bool = False, only_trash: bool = False,
    ) -> list[dict[str, Any]]:
        return self.repo.list(limit=limit, include_trash=include_trash, only_trash=only_trash)

    def dependency_impact(self, pdf_id: str) -> dict[str, Any]:
        return self.repo.dependency_impact(str(pdf_id))

    def trash(self, pdf_id: str, *, actor: str = "USER") -> dict[str, Any]:
        record = self.repo.get(str(pdf_id))
        if not record:
            raise KeyError(f"UNKNOWN_PDF_ASSET:{pdf_id}")
        if str(record.get("lifecycle_status") or "ACTIVE") != "ACTIVE":
            raise RuntimeError(f"PDF_NOT_ACTIVE:{pdf_id}")
        impact = self.dependency_impact(str(pdf_id))
        if impact["reference_count"]:
            raise PermissionError(f"PDF_HAS_REGISTRY_REFERENCES:{pdf_id}")
        source = self._safe_source(record.get("path"), expected_root=self.upload_root)
        if self._inside(source, self.trash_root):
            raise PermissionError(f"ACTIVE_PDF_PATH_INSIDE_TRASH:{source}")
        destination = self.trash_root / source.name
        if destination.exists():
            raise FileExistsError(f"PDF_TRASH_TARGET_EXISTS:{destination.name}")
        shutil.move(str(source), str(destination))
        try:
            self.repo.mark_trashed(
                str(pdf_id), original_path=str(source), trash_path=str(destination.resolve()),
            )
        except Exception:
            shutil.move(str(destination), str(source))
            raise
        self.registry.event(
            "PDF_TRASHED", asset_type="PDF", asset_id=str(pdf_id),
            payload={"actor": actor, "source_path": str(source), "trash_path": str(destination)},
        )
        return {"pdf_id": str(pdf_id), "status": "TRASHED", "trash_path": str(destination)}

    def restore(self, pdf_id: str, *, actor: str = "USER") -> dict[str, Any]:
        record = self.repo.get(str(pdf_id))
        if not record:
            raise KeyError(f"UNKNOWN_PDF_ASSET:{pdf_id}")
        if str(record.get("lifecycle_status") or "ACTIVE") != "TRASHED":
            raise RuntimeError(f"PDF_NOT_TRASHED:{pdf_id}")
        source = self._safe_source(record.get("trash_path") or record.get("path"), expected_root=self.trash_root)
        destination = Path(str(record.get("original_path") or (self.upload_root / source.name))).resolve()
        if not self._inside(destination, self.upload_root) or self._inside(destination, self.trash_root):
            raise PermissionError(f"PDF_RESTORE_PATH_OUTSIDE_UPLOADS:{destination}")
        if destination.exists():
            raise FileExistsError(f"PDF_RESTORE_TARGET_EXISTS:{destination.name}")
        shutil.move(str(source), str(destination))
        try:
            self.repo.mark_active(str(pdf_id), restored_path=str(destination))
        except Exception:
            shutil.move(str(destination), str(source))
            raise
        self.registry.event(
            "PDF_RESTORED", asset_type="PDF", asset_id=str(pdf_id),
            payload={"actor": actor, "restored_path": str(destination)},
        )
        return {"pdf_id": str(pdf_id), "status": "ACTIVE", "path": str(destination)}

    def purge(self, pdf_id: str, *, confirmation: str, actor: str = "USER") -> dict[str, Any]:
        expected = f"DELETE {pdf_id}"
        if confirmation != expected:
            raise PermissionError("PDF_PERMANENT_DELETE_CONFIRMATION_MISMATCH")
        record = self.repo.get(str(pdf_id))
        if not record:
            raise KeyError(f"UNKNOWN_PDF_ASSET:{pdf_id}")
        if str(record.get("lifecycle_status") or "ACTIVE") != "TRASHED":
            raise PermissionError(f"PDF_MUST_BE_TRASHED_BEFORE_PURGE:{pdf_id}")
        impact = self.dependency_impact(str(pdf_id))
        if impact["reference_count"]:
            raise PermissionError(f"PDF_HAS_REGISTRY_REFERENCES:{pdf_id}")
        source = self._safe_source(record.get("trash_path") or record.get("path"), expected_root=self.trash_root)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        cache_target = (self.cache_root / digest).resolve()
        text_index_target = (self.text_index_root / digest).resolve()
        if not self._inside(cache_target, self.cache_root):
            raise PermissionError(f"PDF_CACHE_PATH_OUTSIDE_CACHE_ROOT:{cache_target}")
        if not self._inside(text_index_target, self.text_index_root):
            raise PermissionError(f"PDF_INDEX_PATH_OUTSIDE_INDEX_ROOT:{text_index_target}")
        self.registry.event(
            "PDF_PERMANENT_DELETE_REQUESTED", asset_type="PDF", asset_id=str(pdf_id),
            payload={"actor": actor, "trash_path": str(source)},
        )
        tombstone = source.with_name(source.name + ".deleting")
        if tombstone.exists():
            raise FileExistsError(f"PDF_DELETE_TOMBSTONE_EXISTS:{tombstone.name}")
        source.rename(tombstone)
        try:
            self.repo.delete_trashed(str(pdf_id))
        except Exception:
            tombstone.rename(source)
            raise
        tombstone.unlink()
        if cache_target.is_dir():
            shutil.rmtree(cache_target)
        if text_index_target.is_dir():
            shutil.rmtree(text_index_target)
        self.registry.event(
            "PDF_PERMANENTLY_DELETED", asset_type="PDF", asset_id=str(pdf_id),
            payload={
                "actor": actor, "deleted_path": str(source), "cache_sha256": digest,
                "cache_removed": not cache_target.exists(),
                "text_index_removed": not text_index_target.exists(),
            },
        )
        return {"pdf_id": str(pdf_id), "status": "PURGED", "deleted_path": str(source)}
