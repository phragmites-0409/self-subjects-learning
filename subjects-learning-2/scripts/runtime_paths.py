"""Make the backend's dependency-free runtime resolver available to setup tools."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.runtime import MANIFEST_ROOT, RUNTIME_ROOT, portable_manifest, read_manifest

__all__ = ["MANIFEST_ROOT", "RUNTIME_ROOT", "portable_manifest", "read_manifest"]
