"""Refine an explicit user erasure brush with a local handwriting pixel model.

This model is not reliable enough to erase a whole question automatically.
Only pixels inside the user's brush may be selected, and every result is a draft.
"""
import hashlib,threading
import tempfile
from functools import lru_cache
from pathlib import Path
from PIL import Image
from app.core.errors import AppError
from app.core.runtime import RUNTIME_ROOT, read_manifest

ROOT=RUNTIME_ROOT/'models/exam-ink-seg'
LOCK=threading.Lock()

def configuration():
    try:
        data=read_manifest(ROOT/'manifest.json')
        path=Path(data['onnx_file']).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file():return None
        return data
    except (OSError,ValueError,KeyError,TypeError):return None

def status():
    return {'ready':bool(configuration()),'local':True,'preview_only':True,'engine':'ExamInk-Seg ONNX CPU'}

@lru_cache(maxsize=1)
def engine(path,digest):
    import onnxruntime as ort
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:
        raise AppError('INK_MODEL_INVALID','笔迹模型校验失败',409)
    options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
    # A full-resolution U-Net tile has large temporary tensors. Retaining its
    # arena on this 16GB machine starves the OCR/vision service afterwards.
    options.enable_cpu_mem_arena=False;options.enable_mem_pattern=False
    return ort.InferenceSession(path,sess_options=options,providers=['CPUExecutionProvider'])

def refine(image,marking):
    import cv2
    import numpy as np
    cfg=configuration()
    if not cfg:raise AppError('INK_MODEL_NOT_READY','本地笔迹检测模型尚未准备好',409)
    bbox=marking.getbbox()
    if not bbox:raise AppError('EMPTY_IMAGE_MASK','请先涂抹要处理的笔迹',422)
    l,t,r,b=bbox
    if r-l>960 or b-t>960:
        raise AppError('INK_REGION_TOO_LARGE','请分次标记局部笔记，每次范围不超过960像素',422)
    side=1024
    left=max(0,min(image.width-side,(l+r-side)//2))
    top=max(0,min(image.height-side,(t+b-side)//2))
    right=min(image.width,left+side);bottom=min(image.height,top+side)
    crop=image.convert('RGB').crop((left,top,right,bottom))
    rgb=np.pad(np.asarray(crop),((0,side-crop.height),(0,side-crop.width),(0,0)),mode='edge').astype(np.float32)/255
    rgb=(rgb-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
    with LOCK:
        logits=engine(cfg['onnx_file'],cfg['onnx_sha256']).run(None,{'image':rgb.transpose(2,0,1)[None]})[0]
    if logits.shape!=(1,1,side,side) or not np.isfinite(logits).all():
        raise AppError('INK_MODEL_BAD_OUTPUT','笔迹检测结果无效，未应用擦除',502)
    probability=1/(1+np.exp(-np.clip(logits[0,0],-30,30)))
    # A high threshold limits uncertain pixels. Dilation covers antialiasing,
    # then hard clipping prevents any expansion beyond the user's permission.
    selected=cv2.dilate((probability[:crop.height,:crop.width]>.9).astype('uint8'),np.ones((3,3),np.uint8))*255
    selected[np.asarray(marking.crop((left,top,right,bottom)))==0]=0
    mask=Image.new('L',image.size,0);mask.paste(Image.fromarray(selected),(left,top))
    if not mask.getbbox():
        raise AppError('NO_CONFIDENT_HANDWRITING','所选区域没有检测到足够确定的笔迹，请改用手动擦除或调整标记',422)
    return mask


def page_probabilities(image):
    """Full-detail cached semantic prior, used for classification, never erasure."""
    import numpy as np
    cfg=configuration()
    if not cfg:return None
    rgb=image.convert('RGB');pixels=np.asarray(rgb)
    key=hashlib.sha256((cfg['onnx_sha256']+str(rgb.size)+'full-1024-v1').encode()+pixels.tobytes()).hexdigest()
    directory=RUNTIME_ROOT/'cache/ink-classification';directory.mkdir(parents=True,exist_ok=True)
    cached=directory/f'{key}.npz'
    if cached.is_file():
        try:
            with np.load(cached,allow_pickle=False) as data:probability=data['probability'].astype(np.float32)
            if probability.shape==(rgb.height,rgb.width) and np.isfinite(probability).all():return probability
        except (OSError,ValueError,KeyError):pass
    tile=1024;h,w=pixels.shape[:2];height=max(tile,h);width=max(tile,w)
    pixels=np.pad(pixels,((0,height-h),(0,width-w),(0,0)),mode='edge')
    def starts(size):return sorted(set(list(range(0,max(1,size-tile+1),768))+[size-tile]))
    total=np.zeros((height,width),np.float32);counts=np.zeros_like(total)
    weight=np.maximum(.05,np.outer(np.hanning(tile),np.hanning(tile))).astype(np.float32)
    for top in starts(height):
        for left in starts(width):
            crop=pixels[top:top+tile,left:left+tile].astype(np.float32)/255
            crop=(crop-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
            with LOCK:logits=engine(cfg['onnx_file'],cfg['onnx_sha256']).run(None,{'image':crop.transpose(2,0,1)[None]})[0]
            if logits.shape!=(1,1,tile,tile) or not np.isfinite(logits).all():return None
            probability=1/(1+np.exp(-np.clip(logits[0,0],-30,30)))
            total[top:top+tile,left:left+tile]+=probability*weight;counts[top:top+tile,left:left+tile]+=weight
    probability=(total/np.maximum(counts,.001))[:h,:w]
    with tempfile.NamedTemporaryFile(dir=directory,suffix='.npz',delete=False) as temporary:
        np.savez_compressed(temporary,probability=probability.astype(np.float16));name=temporary.name
    Path(name).replace(cached)
    return probability
