"""Export exactly the Git-visible source files, with a safety audit and checksum.

Does not stage, commit, or publish. Requires a Git repository at the project root.
"""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"runtimes", "归档", "发布包", "data", "node_modules", "dist", "__pycache__", ".git", ".venv"}


def main():
    result = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True)
    names = sorted({name.decode("utf-8") for name in result.stdout.split(b"\0") if name})
    files = []
    for name in names:
        file = ROOT / name
        if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(ROOT):
            raise RuntimeError(f"Unexpected export entry: {name}")
        if FORBIDDEN.intersection(file.relative_to(ROOT).parts) or (file.name.startswith(".env") and file.name != ".env.example"):
            raise RuntimeError(f"Local-only file is visible to Git: {name}")
        if file.stat().st_size > 10 * 1024 * 1024:
            raise RuntimeError(f"Review this large source file before upload: {name}")
        files.append(file)
    output = ROOT / "发布包" / "源码"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "subjects-learning-source.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for file in files:
            package.write(file, file.relative_to(ROOT).as_posix())
    with archive.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"files": len(files), "bytes": archive.stat().st_size, "sha256": sha, "archive": archive.name}
    (output / "source-package.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
