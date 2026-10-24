"""Local ruled-grid geometry; sparse plotted grids remain figures, not prose."""
import math
import re
from io import BytesIO

from PIL import Image


def clustered(values, tolerance=4):
    groups=[]
    for value in sorted(values):
        if groups and value-groups[-1][-1]<=tolerance: groups[-1].append(value)
        else: groups.append([value])
    return [round(sum(group)/len(group)) for group in groups]


def detect_grids(image):
    import cv2
    import numpy as np
    gray=cv2.cvtColor(np.asarray(image.convert("RGB")),cv2.COLOR_RGB2GRAY)
    binary=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,11)
    horizontal=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(max(25,image.width//25),1)))
    vertical=cv2.morphologyEx(binary,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,max(20,image.height//45))))
    segments=cv2.HoughLinesP(binary,1,np.pi/180,threshold=35,minLineLength=max(35,image.width//18),maxLineGap=12)
    h_segments,v_segments=[],[]
    line_mask=np.zeros_like(binary)
    for segment in segments[:,0] if segments is not None else []:
        x0,y0,x1,y1=map(int,segment);dx,dy=abs(x1-x0),abs(y1-y0)
        if dx>max(45,image.width*.08) and dy<=dx*.08:
            h_segments.append((x0,y0,x1,y1));cv2.line(line_mask,(x0,y0),(x1,y1),255,2)
        elif dy>max(35,image.height*.025) and dx<=dy*.08:
            v_segments.append((x0,y0,x1,y1));cv2.line(line_mask,(x0,y0),(x1,y1),255,2)
    connected=cv2.dilate(cv2.bitwise_or(cv2.bitwise_or(horizontal,vertical),line_mask),np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(connected,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    result=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if w<image.width*.12 or h<image.height*.06 or w*h>image.width*image.height*.7: continue
        xs=clustered(np.where((vertical[y:y+h,x:x+w]>0).sum(axis=0)>h*.5)[0].tolist())
        ys=clustered(np.where((horizontal[y:y+h,x:x+w]>0).sum(axis=1)>w*.5)[0].tolist())
        xs=clustered(xs+[(x0+x1)//2-x for x0,y0,x1,y1 in v_segments if x<=min(x0,x1)<=max(x0,x1)<=x+w and abs(y1-y0)>h*.45 and y<=min(y0,y1)<=max(y0,y1)<=y+h],6)
        ys=clustered(ys+[(y0+y1)//2-y for x0,y0,x1,y1 in h_segments if y<=min(y0,y1)<=max(y0,y1)<=y+h and abs(x1-x0)>w*.45 and x<=min(x0,x1)<=max(x0,x1)<=x+w],6)
        if not 3<=len(xs)<=18 or not 3<=len(ys)<=25: continue
        xs=[x+value for value in xs];ys=[y+value for value in ys]
        # A nearby fraction bar can connect to the grid contour. Remove a
        # detached end rule only when it lies well beyond the grid spacing.
        if len(ys)>=6:
            import statistics
            spacing=statistics.median(b-a for a,b in zip(ys,ys[1:]))
            if ys[1]-ys[0]>spacing*1.65:ys=ys[1:]
            if ys[-1]-ys[-2]>spacing*1.65:ys=ys[:-1]
        # Printed glyphs and reaction arrows can form tiny apparent grids.
        if ys[-1]-ys[0]<image.height*.06 or xs[-1]-xs[0]<image.width*.12:
            continue
        if min(b-a for a,b in zip(xs,xs[1:]))<8 or min(b-a for a,b in zip(ys,ys[1:]))<8:
            continue
        result.append({"x":xs,"y":ys,"box":[xs[0]/image.width,ys[0]/image.height,xs[-1]/image.width,ys[-1]/image.height]})
    return result


def grid_content(lines, grid, size):
    width,height=size;xs,ys=grid["x"],grid["y"]
    cells=[[[] for _ in xs[1:]] for _ in ys[1:]]
    for line in lines:
        x=(line.box[0]+line.box[2])*width/2;y=(line.box[1]+line.box[3])*height/2
        row=next((i for i in range(len(ys)-1) if ys[i]<y<ys[i+1]),None)
        col=next((i for i in range(len(xs)-1) if xs[i]<x<xs[i+1]),None)
        if row is not None and col is not None: cells[row][col].append(line)
    occupied=sum(bool(cell) for row in cells for cell in row)
    # A line plot has empty cells or glyphs spanning several cells. Retain its
    # grid, axis numbers, legends and labels together as a complete picture.
    if occupied/max(1,(len(xs)-1)*(len(ys)-1))<.6:
        box=grid["box"];w=box[2]-box[0];h=box[3]-box[1]
        return {"label":"chart","box":[max(0,box[0]-w*.22),max(0,box[1]-.012),min(1,box[2]+w*.22),min(1,box[3]+max(.045,h*.23))],"score":1.0,"geometry":"ruled-grid","grid_box":box},None
    # Merged-cell layouts require a structure model; keep the image when OCR
    # touches a separator rather than inventing a rectangular cell assignment.
    for row in cells:
        for col,cell in enumerate(row):
            if any(line.box[0]*width<xs[col]-3 or line.box[2]*width>xs[col+1]+3 for line in cell):
                return {"label":"table","box":grid["box"],"score":1.0},None
    def escape(text):
        return "".join(r"\backslash " if char=="\\" else "\\"+char if char in "{}%&#_$" else char for char in text)
    rows=[]
    for row in cells:
        rows.append(" & ".join(r"\text{"+escape(" ".join(line.text for line in sorted(cell,key=lambda line:line.box[1])))+"}" for cell in row))
    latex=r"\begin{array}{|"+"c|"*(len(xs)-1)+r"}\hline "+r" \\ \hline ".join(rows)+r" \\ \hline\end{array}"
    return {"label":"table_transcribed","box":grid["box"],"score":1.0},latex


def render_plain_array(formula):
    """Render only our escaped text-cell arrays for PDFs without TeX installed."""
    from pathlib import Path
    from PIL import ImageDraw, ImageFont
    match=re.fullmatch(r"\\begin\{array\}\{(\|(?:c\|)+)\}\\hline\s*(.*?)\\\\\s*\\hline\\end\{array\}",formula,re.S)
    if not match: raise ValueError("Unsupported table formula")
    columns=match[1].count("c")
    rows=[]
    for row in re.split(r"\\\\\s*\\hline\s*",match[2]):
        values=[]
        for cell in re.split(r"(?<!\\)&",row):
            cell_match=re.fullmatch(r"\s*\\text\{((?:\\.|[^{}])*)\}\s*",cell,re.S)
            if not cell_match: raise ValueError("Unsupported table cell")
            value=cell_match[1].replace(r"\backslash ","\\")
            values.append(re.sub(r"\\([{}%&#_$])",r"\1",value))
        if len(values)!=columns: raise ValueError("Invalid table columns")
        rows.append(values)
    if not 2<=len(rows)<=25 or not 2<=columns<=18: raise ValueError("Table too large")
    font_path=Path("C:/Windows/Fonts/simhei.ttf")
    font=ImageFont.truetype(str(font_path),28) if font_path.is_file() else ImageFont.load_default(size=28)
    widths=[min(450,max(100,max(font.getlength(row[col]) for row in rows)+28)) for col in range(columns)]
    image=Image.new("RGB",(math.ceil(sum(widths))+2,50*len(rows)+2),"white")
    draw=ImageDraw.Draw(image)
    x=0
    for col,width in enumerate(widths):
        for row,values in enumerate(rows):
            if font.getlength(values[col])>width-20: raise ValueError("Wide table cell requires review")
            draw.text((x+12,row*50+9),values[col],font=font,fill="#172936")
        draw.line((round(x),0,round(x),image.height),fill="#172936",width=2);x+=width
    draw.line((image.width-1,0,image.width-1,image.height),fill="#172936",width=2)
    for row in range(len(rows)+1):draw.line((0,row*50,image.width,row*50),fill="#172936",width=2)
    buffer=BytesIO();image.save(buffer,"PNG");return buffer.getvalue()
