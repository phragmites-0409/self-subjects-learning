"""Conservative recognition views; no generated strokes or threshold erasure."""
import math
import statistics
import numpy as np
import cv2
from PIL import Image


def normalize_illumination(image):
    rgb=np.asarray(image.convert('RGB'))
    side=min(rgb.shape[:2]);kernel=max(9,min(81,(side//6)|1))
    background=cv2.morphologyEx(rgb,cv2.MORPH_CLOSE,np.ones((kernel,kernel),np.uint8))
    background=cv2.GaussianBlur(background,(0,0),max(1,kernel/5))
    # Divide out paper shading without binarization: decimals, fraction rules,
    # faint dashed curves and small chemical charges retain their gray levels.
    normalized=cv2.divide(rgb,np.maximum(background,1),scale=255)
    smooth=cv2.bilateralFilter(normalized,3,8,3)
    normalized=np.minimum(normalized,smooth)
    gray=cv2.cvtColor(normalized,cv2.COLOR_RGB2GRAY)
    foreground=255-gray
    return Image.fromarray(normalized),Image.fromarray(foreground),Image.fromarray(background)


def rotate_preserving_edges(image,angle):
    if not math.isfinite(angle) or abs(angle)>8:raise ValueError('Unsupported correction angle')
    if abs(angle)<.12:return image.copy()
    w,h=image.size;matrix=cv2.getRotationMatrix2D((w/2,h/2),angle,1)
    cosine,sine=abs(matrix[0,0]),abs(matrix[0,1])
    width=math.ceil(h*sine+w*cosine);height=math.ceil(h*cosine+w*sine)
    matrix[0,2]+=(width-w)/2;matrix[1,2]+=(height-h)/2
    result=cv2.warpAffine(np.asarray(image.convert('RGB')),matrix,(width,height),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_CONSTANT,borderValue=(255,255,255))
    return Image.fromarray(result)


def printed_angle(lines,size=None):
    values=[]
    for line in lines:
        if not getattr(line,'quad',None) or line.score<.93 or len(line.text)<6:continue
        p=np.asarray(line.quad,np.float32)
        if size:p=p*np.array(size,np.float32)
        angle=math.degrees(math.atan2(p[1,1]-p[0,1],p[1,0]-p[0,0]))
        if abs(angle)<=8:values.append(angle)
    if len(values)<3:return 0
    median=statistics.median(values)
    return median if statistics.median(abs(value-median) for value in values)<.65 else 0


def rectify_line(image,line,padding=.35):
    if not getattr(line,'quad',None):
        l,t,r,b=line.box
        height=(b-t)*image.height
        box=(max(0,round(l*image.width)-3),max(0,round(t*image.height-height*padding)),min(image.width,math.ceil(r*image.width)+3),min(image.height,math.ceil(b*image.height+height*padding)))
        return image.crop(box)
    p=np.asarray(line.quad,np.float32)*np.array(image.size,np.float32)
    horizontal=((p[1]-p[0])+(p[2]-p[3]))/2
    vertical=((p[3]-p[0])+(p[2]-p[1]))/2
    w=float(np.linalg.norm(horizontal));h=float(np.linalg.norm(vertical))
    if w<2 or h<2:raise ValueError('Invalid OCR quadrilateral')
    p[0]-=vertical*padding+horizontal*3/w;p[1]-=vertical*padding-horizontal*3/w
    p[2]+=vertical*padding+horizontal*3/w;p[3]+=vertical*padding-horizontal*3/w
    width=math.ceil(w+6);height=math.ceil(h*(1+2*padding))
    if width*height>4_000_000:raise ValueError('Formula view too large')
    target=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],np.float32)
    matrix=cv2.getPerspectiveTransform(p,target)
    result=cv2.warpPerspective(np.asarray(image.convert('RGB')),matrix,(width,height),flags=cv2.INTER_CUBIC,borderValue=(255,255,255))
    return Image.fromarray(result)


def formula_views(image,line):
    original=rectify_line(image,line)
    enhanced,_,_=normalize_illumination(original)
    # Upscaling is interpolation, not generative super-resolution.
    scale=min(3,max(1,96/original.height))
    size=(round(original.width*scale),round(original.height*scale))
    return original.resize(size,Image.Resampling.LANCZOS),enhanced.resize(size,Image.Resampling.LANCZOS)
