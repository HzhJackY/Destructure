from __future__ import annotations

import tempfile
from pathlib import Path

from metadata_registry import MetadataRegistry
from v69_learning import hierarchical_rank, label_entity, seed_label_schemas


def test_versioned_label_schema_and_hierarchical_abstention():
    p=Path(tempfile.gettempdir()) / "v69_learning_contract.sqlite"
    if p.exists(): p.unlink()
    registry=MetadataRegistry(p)
    assert seed_label_schemas(registry) >= 1
    label_entity(registry,schema_id="BLOCK_ROLE_V1",entity_type="TABLE_BLOCK",entity_id="B1",label_value="PRIMARY_TABLE",actor="TEST",evidence={"source":"synthetic"})
    out=hierarchical_rank([{"confidence":.1}],{"company":"A"},[],abstain_threshold=.7)
    assert out["status"]=="ABSTAIN"
    p.unlink()
