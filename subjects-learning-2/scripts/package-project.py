"""Create a private version/data snapshot to restore inside the source repository."""
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parent / "归档" / "版本包"
OUTPUT.mkdir(parents=True, exist_ok=True)
ARCHIVE = OUTPUT / (ROOT.name + "-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".zip")
if ARCHIVE.exists():
    raise RuntimeError("Archive already exists; preserve it under 历史版本包 before creating another snapshot.")
TEMP = ROOT / "data/tmp"
TEMP.mkdir(parents=True, exist_ok=True)
ignored = {"node_modules", "__pycache__", ".pytest_cache", ".ruff_cache", ".git"}
with tempfile.TemporaryDirectory(prefix=ROOT.name + "-package-", dir=TEMP) as temporary:
    snapshot = Path(temporary) / "database.sqlite3"
    database = ROOT / "data/db/subjects-learning.sqlite3"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(snapshot)) as destination:
        source.backup(destination)
        assert destination.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not destination.execute("PRAGMA foreign_key_check").fetchall()
        assets = [r[0] for r in destination.execute("SELECT storage_key FROM assets")]
        contents = [r[0] for r in destination.execute("SELECT content_storage_key FROM question_versions")]
        questions = destination.execute("SELECT count(*) FROM questions").fetchone()[0]
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for directory, directories, filenames in os.walk(ROOT, topdown=True, followlinks=False):
            current = Path(directory)
            relative = current.relative_to(ROOT)
            directories[:] = [d for d in directories if d not in ignored and not (current / d).is_junction()
                              and not (relative == Path("data") and d in {"tmp", "logs"})]
            for name in sorted(filenames):
                if name.endswith((".pyc", ".tsbuildinfo", "-wal", "-shm", ".pid")):
                    continue
                file = current / name
                entry = file.relative_to(ROOT)
                actual = snapshot if entry == Path("data/db/subjects-learning.sqlite3") else file
                archive.write(actual, (Path(ROOT.name) / entry).as_posix())
    with zipfile.ZipFile(ARCHIVE) as archive:
        assert archive.testzip() is None
        names = set(archive.namelist())
        for key in assets + contents:
            assert (Path(ROOT.name) / "data/objects" / key).as_posix() in names, key
        for key in ("backend/app/main.py", "frontend/dist/index.html", "version.json", "scripts/start.ps1", "data/db/subjects-learning.sqlite3"):
            assert (Path(ROOT.name) / key).as_posix() in names
result = {"archive": str(ARCHIVE), "bytes": ARCHIVE.stat().st_size, "entries": len(names),
          "questions": questions, "assets": len(assets), "structured_versions": len(contents),
          "all_referenced_files_packaged": True, "sqlite_integrity": "ok", "zip_integrity": "ok",
          "sha256": hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()}
ARCHIVE.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
