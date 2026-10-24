"""Printed-question filtering and in-place source formula/figure anchors."""
import re,statistics

GRAPHICS={'figure','image','chart','table'}
FORMULAS={'formula','isolate_formula','isolated_formula','display_formula','equation'}

def overlap(a,b):return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]
def enclosed(a,b,p=.006):return a[0]>=b[0]-p and a[1]>=b[1]-p and a[2]<=b[2]+p and a[3]<=b[3]+p
def union(boxes):return [min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]
def chinese(text):return len(re.findall(r'[\u4e00-\u9fff]',text))

def filter_printed(image,lines,elements,probability):
    import cv2
    import numpy as np
    if probability is None:return lines,elements,[]
    gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    background=cv2.morphologyEx(gray,cv2.MORPH_CLOSE,np.ones((61,61),np.uint8))
    ink=cv2.divide(gray,np.maximum(background,1),scale=255)<150
    def ratio(box):
        l,t,r,b=[round(v*s) for v,s in zip(box,[image.width,image.height,image.width,image.height])]
        mask=ink[t:b,l:r];values=probability[t:b,l:r]
        return float((values[mask]>.7).mean()) if mask.any() else 0
    rejected=[];kept=[]
    for element in elements:
        if element['label'] in {'figure','image'} and ratio(element['box'])>.65:
            rejected.append(element['box'])
        else:kept.append(element)
    anchors=[line for line in lines if chinese(line.text)>=5 and ratio(line.box)<.25]
    first=min((line.box[1] for line in anchors),default=0)
    removed=[];retained=[]
    reactions=[line for line in lines if re.match(r'^[①②③④⑤⑥⑦⑧⑨]',line.text) and re.search(r'[HO][0-9₂₃]|→|⇌',line.text)]
    for line in lines:
        value=ratio(line.box)
        footer=bool(re.search(r'第\s*\d+\s*页.*共\s*\d+\s*页',line.text))
        option_label=bool(re.fullmatch(r'\s*[\[（(]?[A-H][\]）).．、]?\s*',line.text))
        handwritten=not option_label and ((chinese(line.text)<=2 and value>.65) or (line.box[3]<first and value>.9))
        reaction_tail=bool(re.search(r'[A-Z][a-z]?[0-9₂₃]|[+→⇌]',line.text)) and any(
            abs((line.box[1]+line.box[3]-anchor.box[1]-anchor.box[3])/2)<max(line.box[3]-line.box[1],anchor.box[3]-anchor.box[1])*.55
            and -.01<=line.box[0]-anchor.box[2]<.1 for anchor in reactions if anchor is not line)
        if reaction_tail:handwritten=False
        if footer or handwritten or any(enclosed(line.box,box,.015) for box in rejected):
            removed.append(line.box)
        else:retained.append(line)
    # Geometry exclusion from OCR is distinct from permission to erase pixels.
    # Rectangles that touch retained print are never advertised as safe erasure.
    notes=[{'label':'handwriting' if not any(overlap(box,line.box) for line in retained) else 'excluded_note','box':box,'source':'exam-ink-seg'} for box in rejected+removed]
    message=[]
    if removed or rejected:message=[f'专用笔迹模型已从题干排除{len(removed)}段笔记／页码，排除{len(rejected)}个误识别笔记图块；未重绘印刷内容']
    return retained,kept+notes,message


def source_layout(lines,figures):
    """Put source formula rows and diagrams back at their reading positions.

    Only used for formula-rich questions. Graphic option matching keeps its
    existing dedicated layout. No formula is inferred from chemistry context.
    """
    if not any(re.search(r'反应|Arrhenius|[A-Z][₀-₉0-9]+|数列|[∑∫√]|[a-z]_[{\d]|\\frac',line.text) for line in lines):return None
    def belongs_to_figure(line,fig):
        if fig.get('grid_box') and line.box[1]<fig['grid_box'][1] and chinese(line.text)>=3:return False
        return enclosed(line.box,fig['box'],.022)
    visible=[line for line in lines if not any(belongs_to_figure(line,fig) for fig in figures)]
    heights=[line.box[3]-line.box[1] for line in visible if chinese(line.text)>=4]
    height=statistics.median(heights) if heights else .025
    glyphs=[line.text_height for line in visible if chinese(line.text)>=4 and line.text_height]
    text_height=statistics.median(glyphs) if glyphs else height*.65
    rows=[]
    for line in sorted(visible,key=lambda line:((line.box[1]+line.box[3])/2,line.box[0])):
        center=(line.box[1]+line.box[3])/2
        if rows and abs(center-rows[-1]['center'])<height*.6:
            rows[-1]['lines'].append(line)
        else:rows.append({'center':center,'lines':[line]})
    events=[]
    for row in rows:
        members=sorted(row['lines'],key=lambda line:line.box[0]);text=''.join(line.text for line in members)
        # Fractions, reaction coefficients and units must retain their geometry.
        chemical=re.findall(r'[A-Z][a-z]?[₀-₉0-9]+',text)
        rich=bool(re.search(r'Δ|[=≠≤≥→⇒]|Arrhenius|反应|历程|[Rr]?\s*ln\s*k',text)) or len(chemical)>=2 and chinese(text)<len(text)*.7
        box=union([line.box for line in members])
        section=bool(re.match(r'^\s*[（(]\d+[）)]',text))
        if rich:
            # Include numerator/denominator fragments around the same row.
            related=[other for other in visible if chinese(other.text)<=1 and box[0]-.01<=other.box[0] and other.box[2]<=box[2]+.02 and box[1]-height*.3<=other.box[1] and other.box[3]<=box[3]+height*.3]
            box=union([box]+[line.box for line in related])
            events.append({'kind':'formula','box':[max(0,box[0]-.003),max(0,box[1]-.003),min(1,box[2]+.003),min(1,box[3]+.003)],'lines':members+related,'label':'原图公式与条件','section':section})
        else:events.append({'kind':'text','box':box,'text':text,'lines':members,'section':section})
    # Remove text fragments already contained in a retained formula row.
    formulas=[event for event in events if event['kind']=='formula']
    events=[event for event in events if event['kind']!='text' or not all(any(enclosed(line.box,f['box'],.008) for f in formulas) for line in event['lines'])]
    groups=[]
    for fig in sorted(figures,key=lambda item:(item['box'][1],item['box'][0])):
        if fig['label'] in FORMULAS:continue
        box=fig['box']
        group=next((g for g in groups if max(0,min(g['box'][3],box[3])-max(g['box'][1],box[1]))/max(.001,min(g['box'][3]-g['box'][1],box[3]-box[1]))>.5),None)
        if group:group['box']=union([group['box'],box])
        else:groups.append({'kind':'diagram','box':list(box),'label':'原题示意图'})
    events+=groups
    # Formula rows and separate figures stay in the original page order.
    events.sort(key=lambda event:(event['box'][1],event['box'][0]))
    # Keep consecutive reaction steps and multiline fractions as one coherent
    # source block. Section headings and diagrams stop the merge.
    merged=[]
    for event in events:
        previous=merged[-1] if merged else None
        if previous and previous['kind'] in ('formula','diagram') and not event.get('section') and event['box'][1]-previous['box'][3]<height*.65:
            previous['box']=union([previous['box'],event['box']])
            previous.setdefault('lines',[]).extend(event.get('lines',[]))
            if event['kind']=='diagram':previous['kind']='diagram';previous['label']='原图条件与示意图'
        else:merged.append(event)
    events=merged
    for previous,event in zip(events,events[1:]):
        if previous['kind']!='text' and event['kind']!='text' and 0<previous['box'][3]-event['box'][1]<height*.8:
            boundary=(previous['box'][3]+event['box'][1])/2
            previous['box'][3]=boundary;event['box'][1]=boundary
    regions=[];paragraphs=[]
    for event in events:
        if event['kind']=='text':paragraphs.append(event['text']);continue
        key=str(len(regions)+1)
        regions.append({'key':key,'kind':event['kind'],'box':event['box'],'label':event['label'],'line_height':text_height})
        paragraphs.append(f'[[图块:{key}]]')
    return '\n'.join(paragraphs),regions
