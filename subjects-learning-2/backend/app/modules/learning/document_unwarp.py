"""UVDoc with a checked sampling mesh; nonlinear correction is preview-only."""
import hashlib
from pathlib import Path
from functools import lru_cache
import numpy as np
from PIL import Image
from app.core.errors import AppError
from app.core.runtime import RUNTIME_ROOT, read_manifest

ROOT=RUNTIME_ROOT/'models/uvdoc'

def configuration():
    try:
        config=read_manifest(ROOT/'manifest.json')
        path=Path(config['grid_path']).resolve()
        if path.is_relative_to(ROOT.resolve()) and path.is_file():return config
    except (OSError,ValueError,KeyError,TypeError):pass
    return None

@lru_cache(maxsize=1)
def engine(path,digest):
    import onnxruntime as ort
    if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise AppError('UNWARP_MODEL_INVALID','矫正模型校验失败',409)
    options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
    options.enable_cpu_mem_arena=False
    return ort.InferenceSession(path,options,providers=['CPUExecutionProvider'])

def clipped_ink_fraction(image,grid):
    """A fold-free mesh can still discard visible source content."""
    import cv2
    from app.modules.learning.document_cv import normalize_illumination
    _,ink,_=normalize_illumination(image)
    foreground=np.asarray(ink)>70
    points=grid.transpose(1,2,0)
    boundary=np.concatenate((points[0],points[1:,-1],points[-1,-2::-1],points[-2:0:-1,0]))
    boundary=(boundary+1)*np.array([image.width-1,image.height-1])/2
    included=np.zeros((image.height,image.width),dtype='uint8')
    cv2.fillPoly(included,[np.round(boundary).astype('int32')],1)
    return float((foreground & (included==0)).sum()/max(1,foreground.sum()))


def unwarp(image):
    config=configuration()
    if not config:raise AppError('UNWARP_MODEL_NOT_READY','文档矫正模型尚未准备好',409)
    rgb=np.asarray(image.convert('RGB'),np.float32)/255
    output,grid=engine(config['grid_path'],config['grid_sha256']).run(None,{'image':rgb.transpose(2,0,1)[None]})
    if output.shape!=(1,3,image.height,image.width) or grid.ndim!=4 or grid.shape[1]!=2 or not np.isfinite(output).all() or not np.isfinite(grid).all():
        raise AppError('UNWARP_INVALID','矫正结果无效，已保留原图',422)
    x,y=grid[0]
    dx_y,dx_x=np.gradient(x);dy_y,dy_x=np.gradient(y)
    jacobian=dx_x*dy_y-dx_y*dy_x
    folding=float((jacobian<=0).mean())
    if folding>.001:raise AppError('UNWARP_FOLDING','矫正出现折叠风险，未生成可采用副本',422)
    clipped=clipped_ink_fraction(image,grid[0])
    if clipped>.005:
        raise AppError('UNWARP_CONTENT_LOSS','矫正可能裁去边缘文字或曲线，已保留原图；请改用背景增强或轻微倾斜校正',422)
    result=np.clip(output[0].transpose(1,2,0)*255,0,255).astype(np.uint8)
    metrics={'folding_fraction':folding,'clipped_ink_fraction':clipped,'source_bounds':[float(x.min()),float(y.min()),float(x.max()),float(y.max())],'preview_only':True,'engine':'UVDoc ONNX'}
    return Image.fromarray(result),metrics
