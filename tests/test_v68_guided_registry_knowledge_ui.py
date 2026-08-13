from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from guided_workflow_ui import render_guided_capture
from metadata_registry import MetadataRegistry
from research_definition_registry import ResearchDefinitionService


class FakeStreamlit:
    def __init__(self):
        self.session_state = {}

    def subheader(self, *args, **kwargs): pass
    def caption(self, *args, **kwargs): pass
    def write(self, *args, **kwargs): pass
    def markdown(self, *args, **kwargs): pass
    def info(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass
    def success(self, *args, **kwargs): pass
    def radio(self, label, options, **kwargs): return list(options)[0] if options else None

    def columns(self, *args, **kwargs):
        class FakeCol:
            def __init__(self, parent): self.parent = parent
            def write(self, *args, **kwargs): pass
            def markdown(self, *args, **kwargs): pass
            def selectbox(self, *args, **kwargs): return self.parent.selectbox(*args, **kwargs)
            def text_input(self, *args, **kwargs): return self.parent.text_input(*args, **kwargs)
            def button(self, *args, **kwargs): return self.parent.button(*args, **kwargs)
        return [FakeCol(self) for _ in range(args[0] if args else 2)]

    def selectbox(self, label, options, **kwargs):
        return list(options)[0] if options else None

    def text_input(self, *args, **kwargs):
        return ""

    def button(self, *args, **kwargs):
        return False
        
    def form(self, *args, **kwargs):
        class FakeForm:
            def __init__(self, parent): self.parent = parent
            def __enter__(self): return self.parent
            def __exit__(self, *args): pass
            def form_submit_button(self, *args, **kwargs): return False
        return FakeForm(self)

    def form_submit_button(self, *args, **kwargs):
        return False


class GuidedRegistryKnowledgeUiTest(unittest.TestCase):
    def test_page_initialization_uses_registry_without_legacy_presets(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = MetadataRegistry(Path(tmp) / "metadata.db")
            definitions = ResearchDefinitionService(registry)
            backend = SimpleNamespace(research_definition_service=definitions)
            render_guided_capture(
                FakeStreamlit(), backend, [],
                lambda path: {"company": "", "year": ""},
            )
            context = definitions.family_discovery_context("financial_investment")
            self.assertEqual(context["registry_family_id"], "financial_investment")
            self.assertEqual(context["preferred_statement_type"], "BALANCE_SHEET")
            self.assertIn("债权投资", context["core_candidates"])


if __name__ == "__main__":
    unittest.main()
