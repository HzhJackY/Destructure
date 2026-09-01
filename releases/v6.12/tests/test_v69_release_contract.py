from __future__ import annotations

from pathlib import Path


def test_v68_is_frozen_and_v69_is_independent_release():
    root=Path(r"C:\dev\AXA_research\releases")
    assert 'APP_VERSION = "v6.8"' in (root/'v6.8'/'version.py').read_text(encoding='utf-8')
    assert 'APP_VERSION = "v6.9"' in (root/'v6.9'/'version.py').read_text(encoding='utf-8')
    assert (root/'v6.9'/'compound_note_engine.py').exists()


def test_v69_multi_table_schema_is_additive():
    source=(Path(r"C:\dev\AXA_research\releases\v6.9")/'metadata_registry.py').read_text(encoding='utf-8')
    for table in ('note_containers','table_blocks','capture_bundles','capture_bundle_children','ml_label_schemas'):
        assert table in source
