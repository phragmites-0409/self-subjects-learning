"""Check the local OCR stack without changing data or downloading anything."""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "subjects-learning-3/backend"))
from app.core.runtime import RUNTIME_ROOT, read_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hashes", action="store_true")
    parser.add_argument("--all-models", action="store_true")
    parser.add_argument("--inference", action="store_true", help="Smoke-test OCR, layout and formula printing locally")
    args = parser.parse_args()
    # Inspect manifests directly so application settings/databases are untouched.
    errors = []
    for name in ("rapidocr", "rapid_layout", "onnxruntime", "cv2", "fastapi", "sqlalchemy"):
        try:
            __import__(name)
            print(f"IMPORT_OK {name}")
        except ImportError as exc:
            errors.append(f"{name}: {exc}")
    for manifest in sorted((ROOT / "dependencies/models").glob("*/manifest.json")):
        name = manifest.parent.name
        installed = RUNTIME_ROOT / "models" / name / "manifest.json"
        if not installed.exists():
            if name == "local-ocr" or args.all_models:
                errors.append(f"Missing manifest: {name}")
            continue
        data = read_manifest(installed)

        def paths(value):
            if isinstance(value, dict):
                for item in value.values():
                    yield from paths(item)
            elif isinstance(value, list):
                for item in value:
                    yield from paths(item)
            elif isinstance(value, str) and Path(value).is_absolute():
                yield Path(value)

        missing = [str(path) for path in paths(data) if not path.exists()]
        if missing and (name == "local-ocr" or args.all_models):
            errors.extend(missing)
        print(f"MODEL {'MISSING' if missing else 'OK'} {name}")
    formula = RUNTIME_ROOT / "formula/Scripts/python.exe"
    if formula.exists():
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        result = subprocess.run([str(formula), "-c", "import numpy, rapid_latex_ocr; print('FORMULA_OK numpy=' + numpy.__version__)"], env=env, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            errors.append(result.stderr)
        else:
            print(result.stdout.strip())
    if args.hashes:
        index = read_manifest(ROOT / "dependencies/models/checksums.json")
        count = 0
        for item in index["files"]:
            path = Path(item["path"])
            if not path.is_file():
                if args.all_models:
                    errors.append(f"Missing indexed artifact: {path}")
                continue
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != item["sha256"] or path.stat().st_size != item["bytes"]:
                errors.append(f"Model checksum mismatch: {path}")
            count += 1
        print(f"SHA256_CHECKED {count} artifacts")
    if args.inference and not errors:
        import numpy as np
        from app.modules.learning.formula_rendering import render
        from app.modules.learning.local_ocr import Runtime
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new('RGB', (700, 160), 'white')
        font = ImageFont.truetype('arial.ttf', 42)
        ImageDraw.Draw(image).text((24, 45), 'TEST 123 x + 1 = 2', font=font, fill='black')
        engine = Runtime(read_manifest(RUNTIME_ROOT / 'models/local-ocr/manifest.json'))
        pixels = np.asarray(image)[:, :, ::-1].copy()
        result = engine.ocr(pixels)
        if not result.txts or not any('123' in text for text in result.txts):
            errors.append('OCR smoke test did not recover the known sample')
        else:
            print('OCR_INFERENCE_OK ' + ' | '.join(result.txts))
        engine.layout(pixels)
        print('LAYOUT_INFERENCE_OK')
        raw, width, height = render('x^2+1')
        if not raw.startswith(b'\x89PNG') or width < 1 or height < 1:
            errors.append('Formula print renderer did not produce a valid PNG')
        else:
            print(f'FORMULA_RENDER_OK {width}x{height}')
        if formula.exists():
            config = read_manifest(RUNTIME_ROOT / 'models/local-ocr/manifest.json')
            result = subprocess.run(
                [str(formula), str(ROOT / 'subjects-learning-3/scripts/local-formula-worker.py')],
                input=json.dumps({'config': config['formula'], 'image': base64.b64encode(raw).decode('ascii')}),
                encoding='utf-8', capture_output=True, timeout=45, check=False,
                env={key: value for key, value in os.environ.items() if key != 'PYTHONPATH'},
            )
            if result.returncode:
                errors.append('Formula recognition worker failed: ' + result.stderr[-500:])
            else:
                recognized = json.loads(result.stdout)['text']
                if not recognized.strip():
                    errors.append('Formula recognition returned no text')
                else:
                    print('FORMULA_INFERENCE_OK ' + recognized)
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(f"RUNTIME_OK {RUNTIME_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
