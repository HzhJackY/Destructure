"""Regression contract for the capture bundle registry write order."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "services" / "capture_service.py"
COMPLETION_SOURCE = ROOT / "services" / "capture_completion_service.py"


def test_child_registry_sync_is_not_nested_in_bundle_graph_transaction():
    """Derived child sync must happen only after the registry transaction closes."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_create_legacy"
    )
    with_lines = []
    sync_lines = []
    for node in ast.walk(method):
        if isinstance(node, ast.With):
            rendered = ast.unparse(node.items[0].context_expr)
            if "self.repo.registry.connect" in rendered:
                with_lines.append((node.lineno, node.end_lineno))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sync_capture_run":
            sync_lines.append(node.lineno)
    assert len(with_lines) == 1
    assert len(sync_lines) >= 2  # primary plus derived child capture(s)
    transaction_start, transaction_end = with_lines[0]
    assert all(not (transaction_start <= line <= transaction_end) for line in sync_lines)


def test_child_sync_failure_is_not_silently_downgraded_to_warning():
    source = SOURCE.read_text(encoding="utf-8")
    assert "CAPTURE_CHILD_REGISTRY_SYNC_FAILED" in source
    assert '"bundle_registration_status"]="CHILD_CAPTURE_REGISTRY_SYNC_FAILED"' in source
    assert "v69_bundle_persistence_warning" not in source


def test_completion_metadata_projection_does_not_run_a_second_readiness_engine():
    source = COMPLETION_SOURCE.read_text(encoding="utf-8")
    assert "capture_readiness" not in source
    assert "decision.to_dict()" in source
    assert '"PENDING_CAPTURE_COMPLETION"' not in source
