from __future__ import annotations

from typing import Any

from metadata_registry import MetadataRegistry, now_iso


class PdfRepository:
    _REFERENCE_COLUMNS = frozenset({"pdf_id", "source_pdf_id", "source_pdf_path", "source_pdf"})

    def __init__(self, registry: MetadataRegistry):
        self.registry = registry

    def list(
        self,
        *,
        limit: int = 5000,
        include_trash: bool = False,
        only_trash: bool = False,
    ) -> list[dict[str, Any]]:
        if only_trash:
            lifecycle_clause = "COALESCE(p.lifecycle_status,'ACTIVE')='TRASHED'"
        elif include_trash:
            lifecycle_clause = "1=1"
        else:
            lifecycle_clause = "COALESCE(p.lifecycle_status,'ACTIVE')='ACTIVE'"
        with self.registry.connect() as conn:
            rows = conn.execute(
                f"""SELECT p.*, COUNT(c.capture_id) capture_reference_count,
                    GROUP_CONCAT(c.capture_id,' | ') capture_run_ids
                    FROM pdf_assets p LEFT JOIN captures c ON c.pdf_id=p.pdf_id
                    WHERE {lifecycle_clause}
                    GROUP BY p.pdf_id
                    ORDER BY COALESCE(p.modified_at,p.updated_at) DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, pdf_id: str) -> dict[str, Any] | None:
        with self.registry.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pdf_assets WHERE pdf_id=?", (str(pdf_id),)
            ).fetchone()
        return dict(row) if row else None

    def dependency_impact(self, pdf_id: str) -> dict[str, Any]:
        """Return every scalar Registry reference to one PDF source identity."""
        record = self.get(pdf_id)
        if not record:
            raise KeyError(f"UNKNOWN_PDF_ASSET:{pdf_id}")
        identities = {
            str(value).strip()
            for value in (
                record.get("pdf_id"), record.get("path"), record.get("original_path"),
                record.get("trash_path"), record.get("filename"), record.get("display_name"),
            )
            if str(value or "").strip()
        }
        references: list[dict[str, Any]] = []
        with self.registry.connect() as conn:
            tables = [
                str(row[0]) for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if str(row[0]) != "pdf_assets"
            ]
            for table in sorted(tables):
                columns = {
                    str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                }
                reference_columns = {
                    column for column in columns
                    if column in self._REFERENCE_COLUMNS
                    or column.endswith("_pdf_id")
                    or column.endswith("_pdf_path")
                }
                for column in sorted(reference_columns):
                    marks = ",".join("?" for _ in identities)
                    count = int(conn.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IN ({marks})',
                        tuple(sorted(identities)),
                    ).fetchone()[0])
                    if count:
                        references.append({"table": table, "column": column, "count": count})
        return {
            "pdf_id": str(pdf_id),
            "reference_count": sum(row["count"] for row in references),
            "references": references,
        }

    def mark_trashed(self, pdf_id: str, *, original_path: str, trash_path: str) -> None:
        with self.registry.connect() as conn:
            cursor = conn.execute(
                """UPDATE pdf_assets
                   SET lifecycle_status='TRASHED',original_path=?,trash_path=?,path=?,trashed_at=?,updated_at=?
                   WHERE pdf_id=? AND COALESCE(lifecycle_status,'ACTIVE')='ACTIVE'""",
                (original_path, trash_path, trash_path, now_iso(), now_iso(), str(pdf_id)),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"PDF_TRASH_STATE_CONFLICT:{pdf_id}")

    def mark_active(self, pdf_id: str, *, restored_path: str) -> None:
        with self.registry.connect() as conn:
            cursor = conn.execute(
                """UPDATE pdf_assets
                   SET lifecycle_status='ACTIVE',path=?,original_path=NULL,trash_path=NULL,trashed_at=NULL,
                       modified_at=?,updated_at=?
                   WHERE pdf_id=? AND lifecycle_status='TRASHED'""",
                (restored_path, now_iso(), now_iso(), str(pdf_id)),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"PDF_RESTORE_STATE_CONFLICT:{pdf_id}")

    def delete_trashed(self, pdf_id: str) -> None:
        with self.registry.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM pdf_assets WHERE pdf_id=? AND lifecycle_status='TRASHED'",
                (str(pdf_id),),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"PDF_PURGE_STATE_CONFLICT:{pdf_id}")
