from pathlib import Path

from tools.release_source_bootstrap import audit, backfill_missing


def test_backfill_copies_only_missing_allowed_source_files(tmp_path):
    reference = tmp_path / "reference"; target = tmp_path / "target"
    reference.mkdir(); target.mkdir()
    (reference / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (reference / "docs").mkdir(); (reference / "docs" / "contract.md").write_text("contract", encoding="utf-8")
    (reference / "output").mkdir(); (reference / "output" / "job.json").write_text("{}", encoding="utf-8")
    (reference / "CURRENT_TASK_ANALYSIS.md").write_text("transient", encoding="utf-8")
    (target / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    result = backfill_missing(reference, target)
    assert result["missing_allowed_files"] == []
    assert [item["path"] for item in result["copied_missing_files"]] == ["docs/contract.md"]
    assert (target / "module.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert not (target / "output" / "job.json").exists()
    assert audit(reference, target)["different_hash_files"] == ["module.py"]
