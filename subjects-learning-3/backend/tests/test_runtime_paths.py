"""Portability and containment checks for offline model configuration."""
from pathlib import Path

import pytest
from app.core import runtime


def test_manifests_follow_runtime_after_relocation(tmp_path, monkeypatch):
    relocated = tmp_path / "另一个目录" / "runtimes"
    monkeypatch.setattr(runtime, "RUNTIME_ROOT", relocated)
    original = {
        "files": [{"path": "runtime:/models/glm-ocr/model.gguf"}],
        "source": "https://example.org/model",
        "formula_python": "runtime:/formula/Scripts/python.exe",
    }
    resolved = runtime.resolve_manifest(original)
    assert Path(resolved["files"][0]["path"]) == relocated / "models/glm-ocr/model.gguf"
    assert resolved["source"] == original["source"]
    assert runtime.portable_manifest(resolved) == original


@pytest.mark.parametrize("path", ["runtime:/../outside/model.onnx", "runtime:/models/../../outside"])
def test_model_paths_cannot_escape_runtime(path):
    with pytest.raises(ValueError, match="escapes"):
        runtime.resolve_manifest({"model": path})
