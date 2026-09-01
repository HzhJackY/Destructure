"""API-ready orchestration facade for v6.4 discovery lifecycle."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from generic_discovery import discover, hierarchical_backoff


class DiscoveryService:
    def __init__(self, discovery_registry, cache_root: Path):
        self.registry = discovery_registry
        self.cache_root = Path(cache_root) / "statement_indexes"

    def preview(self, pdf_path: Path, *, display_name: str, company: str = "", report_year: str = "",
                filing_type: str = "ANNUAL_REPORT", preset_name: str | None = None) -> list[dict[str, Any]]:
        rows = discover(pdf_path, self.cache_root, display_name=display_name, company=company,
                        report_year=report_year, filing_type=filing_type, preset_name=preset_name)
        for row in rows:
            row["pdf_id"] = str(pdf_path)
            self.registry.save_machine(row)
        return rows

    def fast_path_preview(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        return hierarchical_backoff(query, self.registry.fast_path(query))

    def adjudicate(self, discovery_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.registry.adjudicate(discovery_id, **kwargs)

