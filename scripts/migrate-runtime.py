"""Copy and SHA-256 verify the existing Windows runtime; preserve the source.

Run explicitly with --source-python and --source-runtime. No downloads, deletion,
or traversal into junctions. Logs and download fragments are not dependencies.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"__pycache__", ".pytest_cache", ".ruff_cache", "download-parts", "service", "test", "tests", ".vite", ".vite-temp"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_tree(source, target, report):
    if not source.is_dir():
        return
    for directory, folders, files in os.walk(source, followlinks=False):
        current = Path(directory)
        folders[:] = [name for name in folders if name not in SKIP
                      and not name.endswith("-download-parts")
                      and not (current / name).is_junction()
                      and not (current / name).is_symlink()
                      and not name.startswith(("agreement_echo", "subjects_learning"))]
        for name in files:
            if name.startswith("__editable__") or name.endswith((".pyc", ".pyo", ".log", ".pid", ".part")):
                continue
            original = current / name
            if original.is_symlink():
                raise RuntimeError(f"Unexpected symbolic link: {original}")
            destination = target / original.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
            expected = digest(original)
            if digest(destination) != expected:
                raise RuntimeError(f"Copy verification failed: {destination}")
            report.append({"path": destination.relative_to(ROOT).as_posix(), "bytes": destination.stat().st_size, "sha256": expected})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-python", type=Path, required=True)
    parser.add_argument("--source-runtime", type=Path, required=True)
    args = parser.parse_args()
    target = ROOT / "runtimes"
    if (target / "migration-report.json").exists():
        raise RuntimeError("A verified migration already exists; do not overwrite it")
    report = []
    python = target / "python"
    python.mkdir(parents=True, exist_ok=True)
    for name in ["DLLs", "Lib", "libs", "include", "tcl"]:
        copy_tree(args.source_python / name, python / name, report)
    for original in args.source_python.iterdir():
        if original.is_file() and original.suffix in {".exe", ".dll", ".txt"}:
            destination = python / original.name
            shutil.copy2(original, destination)
            expected = digest(original)
            assert digest(destination) == expected
            report.append({"path": destination.relative_to(ROOT).as_posix(), "bytes": destination.stat().st_size, "sha256": expected})
    # python -m ruff delegates to this native binary; copied pip.exe launchers
    # have absolute interpreter paths and are intentionally not used.
    source_ruff = args.source_python / 'Scripts/ruff.exe'
    if source_ruff.is_file():
        destination = python / 'Scripts/ruff.exe'
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_ruff, destination)
        expected = digest(source_ruff)
        assert digest(destination) == expected
        report.append({"path": destination.relative_to(ROOT).as_posix(), "bytes": destination.stat().st_size, "sha256": expected})
    print("Verified base Python", flush=True)
    for name in ["local-ocr-packages", "models", "formula", "document-ocr", "document-renderer", "ink-erase", "node_modules"]:
        before = len(report)
        copy_tree(args.source_runtime / name, target / name, report)
        print(f"Verified {name}: {len(report)-before} files", flush=True)
    result = {"created_utc": datetime.now(timezone.utc).isoformat(), "source_python": str(args.source_python), "source_runtime": str(args.source_runtime), "files": report, "total_bytes": sum(item["bytes"] for item in report), "configuration_note": "Copied-byte hashes precede portable manifest and pyvenv.cfg rewrites. Model binaries have a separate committed checksum index."}
    (target / "migration-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for manifest in (ROOT / 'dependencies/models').glob('*/manifest.json'):
        shutil.copy2(manifest, target / 'models' / manifest.parent.name / 'manifest.json')
    published = ROOT / 'subjects-learning-2/data/models/local-ocr/manifest.json'
    published.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'dependencies/models/local-ocr/manifest.json', published)
    subprocess.run([str(python / 'python.exe'), str(ROOT / 'scripts/repair-runtime.py')], check=True)
    print(f"COPY_VERIFIED {len(report)} files, {result['total_bytes']/1024**3:.2f} GiB. Source preserved.", flush=True)


if __name__ == "__main__":
    main()
