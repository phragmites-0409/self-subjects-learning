"""Repository-local engines and portable model manifests, independent of cwd."""
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = PROJECT_ROOT.parent
_CONFIG = json.loads((REPOSITORY_ROOT / "runtime.json").read_text(encoding="utf-8-sig"))
RUNTIME_ROOT = Path(os.environ.get("SUBJECTS_LEARNING_RUNTIME", REPOSITORY_ROOT / _CONFIG["root"])).resolve()
MANIFEST_ROOT = REPOSITORY_ROOT / "dependencies" / "models"


def resolve_manifest(value):
    """Expand only explicit runtime:/ URIs; leave URLs and ordinary text alone."""
    if isinstance(value, dict):
        return {key: resolve_manifest(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_manifest(item) for item in value]
    if isinstance(value, str) and value.startswith("runtime:/"):
        path = (RUNTIME_ROOT / value[len("runtime:/"):]).resolve()
        if not path.is_relative_to(RUNTIME_ROOT):
            raise ValueError("Model path escapes the configured runtime directory")
        return str(path)
    return value


def portable_manifest(value):
    """Serialize paths relative to the runtime without machine-specific prefixes."""
    if isinstance(value, dict):
        return {key: portable_manifest(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_manifest(item) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        path = Path(value).resolve()
        if path.is_relative_to(RUNTIME_ROOT):
            return "runtime:/" + path.relative_to(RUNTIME_ROOT).as_posix()
    return value


def read_manifest(path):
    return resolve_manifest(json.loads(Path(path).read_text(encoding="utf-8")))
