from pathlib import Path


def test_offline_rebuild_uses_only_fixed_companion_inputs() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "tools" / "rebuild_windows_portable_from_companion.ps1").read_text(encoding="utf-8")

    assert "python_runtime_input_lock.csv" in script
    assert "pip_bootstrap_lock.csv" in script
    assert "tesseract_runtime_files" in script
    assert "tessdata_fast_lock.csv" in script
    assert "Assert-Hash" in script
    assert "Expand-Archive" in script
    assert "PythonRequirementsLock" in script
    assert "build_windows_portable_prerelease.ps1" in script
    assert "Refusing to overwrite work directory" in script
    assert "Unsafe path relationship" in script
    assert "Test-IsWithin" in script
    assert "Invoke-WebRequest" not in script
    assert "curl" not in script.lower()
