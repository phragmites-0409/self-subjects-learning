from pathlib import Path
import sqlite3
import zipfile

root = Path(__file__).resolve().parents[1]
target = root / "data/backups/10月5日-星期一-开发前"
target.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(target / "source-and-objects.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for folder in ("backend", "frontend/src", "frontend/public", "scripts", "data/objects"):
        for p in (root / folder).rglob("*"):
            if p.is_file() and not any(part in p.parts for part in ("__pycache__", ".pytest_cache")):
                archive.write(p, p.relative_to(root))
    for name in ("pyproject.toml", "frontend/package.json", "frontend/package-lock.json", "docs/项目资料/项目功能逻辑与用户使用链路.md"):
        if (root / name).exists():
            archive.write(root / name, name)
database = root / "data/db/subjects-learning.sqlite3"
if database.exists():
    with sqlite3.connect(database) as source, sqlite3.connect(target / database.name) as destination:
        source.backup(destination)
print("Backup completed")
