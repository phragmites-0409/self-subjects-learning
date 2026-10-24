"""Run with the formula environment, isolated from the NumPy 2 OCR runtime."""

import json
import shutil
import sys
import os
from pathlib import Path
from runtime_paths import RUNTIME_ROOT, portable_manifest, read_manifest

from rapid_latex_ocr import LaTeXOCR

target = Path(os.environ.get("LOCAL_OCR_MODEL_DIR", str(RUNTIME_ROOT / "models/local-ocr")))
manifest_path = target / "manifest.json"
manifest = read_manifest(manifest_path)
names = ("image_resizer_path", "encoder_path", "decoder_path", "tokenizer_json")
cached = manifest.get("formula", {})
if all(name in cached and Path(cached[name]).is_file() for name in names):
    engine = LaTeXOCR(**cached)
else:
    engine = LaTeXOCR()
formula = {}
for name in names:
    source = Path(getattr(engine, name))
    dest = target / ("formula-" + source.name)
    if source.resolve() != dest.resolve():
        shutil.copy2(source, dest)
    formula[name] = str(dest)
manifest.update(formula=formula, formula_python=sys.executable)
manifest_path.write_text(
    json.dumps(portable_manifest(manifest), ensure_ascii=False, indent=2), encoding="utf-8"
)
published = Path(__file__).resolve().parents[1] / "data/models/local-ocr/manifest.json"
published.parent.mkdir(parents=True, exist_ok=True)
published.write_text(json.dumps(portable_manifest(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
print("LOCAL_FORMULA_READY", flush=True)
