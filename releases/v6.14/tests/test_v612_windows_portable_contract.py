from __future__ import annotations

from pathlib import Path


def test_portable_builder_declares_embedded_runtime_and_chinese_ocr_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    builder = (root / "tools" / "build_windows_portable_prerelease.ps1").read_text(encoding="utf-8")

    assert "chi_sim.traineddata" in builder
    assert "TESSDATA_PREFIX" in builder
    assert "FIN_METRIC_DATA_HOME" in builder
    assert "Refusing to overwrite existing portable directory" in builder
    assert "PythonRequirementsLock" in builder
    assert "--require-hashes" in builder
    assert "TesseractRuntimeClosureCsv" in builder
    assert "ThirdPartyEvidenceHome" in builder
    assert "(Join-Path $Destination 'THIRD_PARTY')" in builder
    assert "--no-compile" in builder
    assert "'__pycache__'" in builder
    assert "^\\.\\./\\.\\./bin/" in builder


def test_portable_document_retains_pre_release_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    document = (root / "docs" / "windows_portable_prerelease.md").read_text(encoding="utf-8")

    assert "NOT_PRODUCTION_RELEASE_CERTIFIED" in document
    assert "Tesseract `5.5.3`" in document
    assert "chi_sim" in document
    assert "不包含任何真实 PDF" in document
