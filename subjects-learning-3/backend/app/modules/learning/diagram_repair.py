"""Offline, explicitly masked LaMa repair. Never modify pixels outside the mask."""
import hashlib
import threading
from functools import lru_cache
from pathlib import Path
from PIL import Image
from app.core.errors import AppError
from app.core.runtime import RUNTIME_ROOT, read_manifest

MODEL_ROOT = RUNTIME_ROOT / 'models/diagram-repair'
LOCK = threading.Lock()


def configuration():
    try:
        manifest = read_manifest(MODEL_ROOT/'manifest.json')
        model = (MODEL_ROOT/'lama_fp32.onnx').resolve()
        if Path(manifest['model']).resolve() != model or not model.is_file():
            return None
        return manifest
    except (OSError,ValueError,KeyError,TypeError):
        return None


def status():
    return {'ready': bool(configuration()), 'engine': 'LaMa ONNX CPU', 'local': True}


@lru_cache(maxsize=1)
def session(model, digest):
    import onnxruntime as ort
    if hashlib.sha256(Path(model).read_bytes()).hexdigest() != digest:
        raise AppError('LOCAL_REPAIR_INVALID','本地图像修复模型校验失败',409)
    options = ort.SessionOptions()
    options.intra_op_num_threads=4
    options.inter_op_num_threads=1
    return ort.InferenceSession(model,sess_options=options,providers=['CPUExecutionProvider'])


def repair(image, mask):
    import numpy as np
    config = configuration()
    if not config:
        raise AppError('LOCAL_REPAIR_NOT_READY','本地图像修复模型尚未就绪',409)
    box = mask.getbbox()
    if not box:
        raise AppError('EMPTY_IMAGE_MASK','请标记需要修复的笔迹',422)
    # Context is limited to the marked neighbourhood, retaining full detail on
    # large photographs. The final composite preserves all unmarked pixels.
    left,top,right,bottom=box
    context=max(64,min(256,max(right-left,bottom-top)))
    region=(max(0,left-context),max(0,top-context),min(image.width,right+context),min(image.height,bottom+context))
    crop=image.convert('RGB').crop(region)
    local_mask=mask.crop(region)
    side=max(crop.size)
    padded=Image.fromarray(np.pad(np.asarray(crop),((0,side-crop.height),(0,side-crop.width),(0,0)),mode='reflect' if min(crop.size)>1 else 'edge'))
    padded_mask=Image.new('L',(side,side),0)
    padded_mask.paste(local_mask,(0,0))
    rgb=np.asarray(padded.resize((512,512),Image.Resampling.LANCZOS))
    marking=np.asarray(padded_mask.resize((512,512),Image.Resampling.NEAREST))
    feeds={'image':rgb.transpose(2,0,1)[None].astype(np.float32)/255.,'mask':(marking[None,None]>0).astype(np.float32)}
    with LOCK:
        output=session(config['model'],config['sha256']).run(None,feeds)[0]
    output=np.asarray(output)[0]
    if output.shape[0]==3:
        output=output.transpose(1,2,0)
    if output.max()<=1.5:
        output=output*255.
    candidate=Image.fromarray(np.clip(output,0,255).astype(np.uint8)).resize((side,side),Image.Resampling.LANCZOS).crop((0,0,*crop.size))
    patch=crop.copy()
    patch.paste(candidate,mask=local_mask)
    result=image.copy()
    result.paste(patch,region[:2])
    return result
