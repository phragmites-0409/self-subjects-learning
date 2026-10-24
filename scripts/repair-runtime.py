"""Refresh isolated venv launchers after moving this checkout (no downloads)."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
config = json.loads((ROOT / "runtime.json").read_text(encoding="utf-8-sig"))
runtime = Path(os.environ.get("SUBJECTS_LEARNING_RUNTIME", ROOT / config["root"])).resolve()
base = Path(sys.base_prefix)
for name in ("formula", "ink-erase"):
    path = runtime / name / "pyvenv.cfg"
    if not path.is_file():
        continue
    lines = path.read_text(encoding="utf-8").splitlines()
    values = dict(line.split(" = ", 1) for line in lines if " = " in line)
    values.update(home=str(base), executable=str(base / "python.exe"), command=f"{sys.executable} -m venv {path.parent}")
    content = "\n".join(f"{key} = {value}" for key, value in values.items()) + "\n"
    if path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
        print(f"Updated {name}/pyvenv.cfg")
