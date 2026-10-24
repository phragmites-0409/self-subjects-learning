"""Render the same supported math/chemistry syntax used by the browser."""
import json,subprocess,shutil
from pathlib import Path
from functools import lru_cache
from PIL import Image
from app.core.runtime import RUNTIME_ROOT

ROOT=Path(__file__).resolve().parents[4]
CACHE=RUNTIME_ROOT/'cache/formula-render'

def ready():
    return shutil.which('node') is not None and (RUNTIME_ROOT/'document-renderer/node_modules/mathjax-full/js/mathjax.js').is_file()

@lru_cache(maxsize=128)
def render(formula):
    if not ready():raise ValueError('Local formula renderer is not installed')
    try:
        process=subprocess.run([shutil.which('node'),str(ROOT/'scripts/render-intake-formula.cjs')],input=json.dumps({'formula':formula}),encoding='utf-8',capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.TimeoutExpired) as exc:
        # PDF formatting retains the source formula on ValueError.
        raise ValueError('Local formula renderer unavailable') from exc
    try:result=json.loads(process.stdout)
    except ValueError:raise ValueError('Local formula renderer failed: '+process.stderr[-300:]) from None
    if process.returncode or not result.get('valid'):raise ValueError(result.get('error','Formula rendering failed'))
    path=Path(result['path']).resolve()
    if not path.is_relative_to(CACHE.resolve()):raise ValueError('Invalid renderer output path')
    with Image.open(path) as image:width,height=image.size
    return path.read_bytes(),width,height
