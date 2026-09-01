from hierarchical_child_discovery import HierarchicalChildTableDiscoveryService


def test_stage_b_only_skips_explicitly_excluded_member_statuses(tmp_path):
    service = HierarchicalChildTableDiscoveryService(repository=None, index_service=None)

    class Index:
        def build(self, _pdf):
            return {
                "index_id": "IDX",
                "source_pdf_sha256": "sha",
                "source_pdf_id": "pdf",
                "cache_hit": False,
                "index_build_ms": 0,
            }

        def headings(self, _index_id):
            return []

    class Repo:
        def cached_discovery(self, **_kwargs):
            return {"run": {"status": "CACHED"}, "candidates": []}

    service.index = Index()
    service.repo = Repo()
    base = {
        "anchor_id": "A",
        "anchor_child_id": "C",
        "raw_label": "债权投资",
        "statement_scope": "CONSOLIDATED",
    }
    unresolved = service.discover(
        tmp_path / "dummy.pdf",
        {"occurrence_id": "A"},
        {**base, "member_period_status": "UNRESOLVED"},
        {"canonical_title": "债权投资"},
        "CONSOLIDATED",
    )
    assert unresolved["run"]["status"] == "CACHED"

    excluded = service.discover(
        tmp_path / "dummy.pdf",
        {"occurrence_id": "A"},
        {**base, "member_period_status": "OUTSIDE_FAMILY"},
        {"canonical_title": "债权投资"},
        "CONSOLIDATED",
    )
    assert excluded["early_stop_reason"] == "NON_CURRENT_MEMBER_OUTSIDE_FAMILY"
