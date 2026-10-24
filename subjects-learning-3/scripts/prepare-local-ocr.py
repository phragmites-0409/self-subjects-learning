"""Prepare explicit offline model paths; only this setup command may download."""

import argparse
import hashlib
import importlib.util
import json
import shutil
import os
from runtime_paths import RUNTIME_ROOT, portable_manifest, read_manifest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument(
    "--layout",
    default="doclayout_docstructbench",
    choices=["doclayout_docstructbench", "pp_layout_cdla"],
)
args = parser.parse_args()
target = Path(os.environ.get("LOCAL_OCR_MODEL_DIR", str(RUNTIME_ROOT / "models/local-ocr")))
target.mkdir(parents=True, exist_ok=True)


def package_dir(name):
    return Path(importlib.util.find_spec(name).origin).parent


def copy_model(source, name):
    dest = target / name
    shutil.copy2(source, dest)
    return str(dest.resolve())


ocr_models = package_dir("rapidocr") / "models"
ocr = {
    "Det.model_path": copy_model(
        ocr_models / "PP-OCRv6_det_small.onnx", "text-det.onnx"
    ),
    "Cls.model_path": copy_model(
        ocr_models / "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "text-cls.onnx"
    ),
    "Rec.model_path": copy_model(
        ocr_models / "PP-OCRv6_rec_small.onnx", "text-rec.onnx"
    ),
    "EngineConfig.onnxruntime.intra_op_num_threads": 4,
    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
}
from rapid_layout import ModelType
from rapid_layout.model_handler.utils import ModelProcessor

cached = target / "layout-docstructbench.onnx"
if (
    args.layout == "doclayout_docstructbench"
    and cached.exists()
    and hashlib.sha256(cached.read_bytes()).hexdigest()
    == ModelProcessor.model_map[args.layout]["SHA256"]
):
    layout_model = cached
else:
    layout_model = ModelProcessor.get_model_path(ModelType(args.layout))
layout = {
    "model_type": args.layout,
    "model_dir_or_path": copy_model(layout_model, "layout.onnx"),
    "engine_cfg": {"intra_op_num_threads": 4, "inter_op_num_threads": 1},
    "conf_thresh": 0.5,
}
manifest = {"ocr": ocr, "layout": layout}
old = target / "manifest.json"
if old.exists():
    previous = read_manifest(old)
    manifest.update(
        {key: previous[key] for key in ("formula", "formula_python") if key in previous}
    )

# Warm up constructors before publishing readiness; runtime never downloads models.
from rapid_layout import RapidLayout
from rapidocr import RapidOCR

RapidOCR(params=ocr)
RapidLayout(**layout)
old.write_text(json.dumps(portable_manifest(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
published = ROOT / "data/models/local-ocr/manifest.json"
published.parent.mkdir(parents=True, exist_ok=True)
published.write_text(json.dumps(portable_manifest(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
print("LOCAL_MODELS_READY", target, flush=True)
