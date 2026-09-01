from __future__ import annotations
from typing import Any
from metadata_registry import MetadataRegistry


class PdfRepository:
    def __init__(self,registry:MetadataRegistry):self.registry=registry
    def list(self,*,limit:int=5000)->list[dict[str,Any]]:
        with self.registry.connect() as conn:
            rows=conn.execute('''SELECT p.*, COUNT(c.capture_id) capture_reference_count,
                GROUP_CONCAT(c.capture_id,' | ') capture_run_ids
                FROM pdf_assets p LEFT JOIN captures c ON c.pdf_id=p.pdf_id
                GROUP BY p.pdf_id ORDER BY COALESCE(p.modified_at,p.updated_at) DESC LIMIT ?''',(int(limit),)).fetchall()
        return [dict(r) for r in rows]
