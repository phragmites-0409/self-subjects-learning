"""Small, spatially located math atoms with conservative local-model acceptance.

Model probability is a rejection signal, never a claim of transcription accuracy.
No chemistry balancing, solving or reconstruction of hidden print is performed.
"""
import math
import re
import statistics
import time
from dataclasses import replace

from app.modules.learning import document_cv, local_document_ocr
from app.modules.learning.printed_document import chinese, enclosed, union, GRAPHICS
from app.modules.learning.reading_order import paragraphs

CHINESE = re.compile(r'[\u4e00-\u9fff]')
DELIMITERS = set('，。；：:、？！“”「」')
STYLE = {'quad', 'qquad', 'mathrm', 'operatorname', 'text', 'left', 'right', 'displaystyle', 'mathit', 'big', 'Big', 'bigg', 'tiny', 'small'}


def canonical(text):
    text=text.strip()
    if text.startswith('$$') and text.endswith('$$'):text=text[2:-2]
    elif text.startswith('$') and text.endswith('$'):text=text[1:-1]
    elif text.startswith((r'\[',r'\(')) and text.endswith((r'\]',r'\)')):text=text[2:-2]
    text=text.strip().replace(r'\dfrac',r'\frac').replace(r'\tfrac',r'\frac')
    text=re.sub(r'\\(?:left|right)(?![a-zA-Z])','',text)
    # Preserve the terminator of control words: \\Delta H must never become
    # the nonexistent command \\DeltaH after whitespace normalization.
    text=re.sub(r'(\\[A-Za-z]+)\s+(?=[A-Za-z])',r'\1{}',text)
    return re.sub(r'\s+','',text)


def critical_weak_tokens(result,source=''):
    weak=[]
    for token in result.get('weak_tokens',[]):
        text=token['token'].strip()
        # Ignore only typography. Digits, phase letters, signs and arrows remain
        # critical even when part of a command, e.g. \\Delta or \\frac.
        residue=re.sub(r'[\s\\{}()]','',text)
        corroborated=residue=='Delta' and bool(re.search('[Δ∆]',source))
        if residue and residue not in STYLE and not corroborated:weak.append(token)
    return weak


def accepted(results, threshold=.985, source='', words=None):
    if len(results)!=2 or any(result.get('finish_reason')!='stop' for result in results):return False,'输出不完整'
    if not canonical(results[0]['text']) or canonical(results[0]['text'])!=canonical(results[1]['text']):return False,'两种图像视图转录不一致'
    if any(not isinstance(result.get('mean_probability'),(int,float)) or not math.isfinite(result['mean_probability']) or not threshold<=result['mean_probability']<=1 for result in results):return False,'整体置信门槛未通过'
    if any(critical_weak_tokens(result,source) for result in results):return False,'数字、符号或字母置信不足'
    text=canonical(results[0]['text'])
    flattened=re.sub(r'\\(?:mathrm|text|operatorname)\{([^{}]*)\}',r'\1',text)
    if source.count('+')>flattened.count('+'):return False,'原图加号未完整保留'
    if any(source.count(sign)>flattened.count(sign) for sign in ('>','<','≥','≤')):return False,'不等号未完整保留'
    if words:
        evidence='';scores=[]
        for word in words:
            fragment=word['text'].translate(str.maketrans('₀₁₂₃₄₅₆₇₈₉','0123456789'))
            evidence+=fragment;scores.extend([word.get('score',0)]*len(fragment))
        plain=re.sub(r'[{}_]','',re.sub(r'\\[A-Za-z]+','',flattened))
        for match in re.finditer(r'[A-Z][a-z]?\d+',evidence):
            if min(scores[match.start():match.end()] or [0])>=threshold and match[0] not in plain:
                return False,'印刷数字与独立字框证据不一致'
    # Two views share the same model and may share the same mistake. Literal
    # phase evidence from the independent character OCR vetoes (l) -> (1).
    for phase in re.findall(r'\(([gls])\)',source):
        if f'({phase})' not in flattened:return False,'物态符号与字框识别证据不一致'
    if re.search(r'[A-Z][A-Za-z0-9]*[.•·](?:$|→)',source) and not re.search(r'\\(?:cdot|bullet)|[•·]',text):return False,'自由基点号与原图字框证据不一致'
    if '(' in flattened or ')' in flattened:
        if flattened.count('(')!=flattened.count(')') or '()' in flattened:return False,'括号边界未通过复核'
    if len(text)>2500 or CHINESE.search(text) or re.search(r'```|<[A-Za-z]+(?:\s|>)|https?://|待|答案|therefore',text,re.I):return False,'不是独立且完整的公式'
    from app.modules.learning.formula_rendering import render
    try:render(text)
    except (OSError,ValueError,RuntimeError,TimeoutError):return False,'公式排版校验未通过'
    return True,''


def chemical_atom(source,words,results,threshold):
    """Typeset literal high-confidence print, corroborated by both model views.

    Very small chemical atoms often include neighboring Chinese in an OCR crop.
    Only the exact character-OCR atom may be returned here, never model extras.
    """
    source=source.translate(str.maketrans('₀₁₂₃₄₅₆₇₈₉','0123456789'))
    outer=source.startswith('(') and source.endswith(')')
    atom=source[1:-1] if outer else source
    if not re.fullmatch(r'(?:[A-Z][a-z]?[0-9]{0,2}){1,8}',atom) or not re.search(r'\d',atom):return None
    if any(word.get('score',0)<threshold for word in words):return None
    def plain(text):
        text=canonical(text)
        text=re.sub(r'\\(?:mathrm|text|operatorname)\{([^{}]*)\}',r'\1',text)
        text=re.sub(r'\\[A-Za-z]+','',text)
        return re.sub(r'[{}_\s]','',text)
    if len(results)!=2 or any(result.get('finish_reason')!='stop' or atom not in plain(result['text']) for result in results):return None
    # A different index next to the matched atom is contradictory, not padding.
    if any(re.search(re.escape(atom)+r'\d',plain(result['text'])) for result in results):return None
    latex=''.join(r'\mathrm{'+symbol+'}'+('_{'+count+'}' if count else '') for symbol,count in re.findall(r'([A-Z][a-z]?)(\d*)',atom))
    return ('('+latex+')') if outer else latex


def combine_rows(lines,image):
    """Spatially combine split physical rows, keeping their character geometry."""
    if not lines:return []
    glyph=statistics.median([line.text_height for line in lines if line.text_height and chinese(line.text)>=3] or [line.text_height for line in lines if line.text_height] or [.025])
    angle=document_cv.printed_angle(lines,image.size)
    slope=math.tan(math.radians(angle))*image.width/image.height
    def y(line):return (line.box[1]+line.box[3])/2-slope*(line.box[0]+line.box[2])/2
    rows=[]
    for line in sorted(lines,key=lambda line:(y(line),line.box[0])):
        row=next((row for row in reversed(rows[-3:]) if abs(y(line)-row['y'])<glyph*.40),None)
        if row:row['members'].append(line)
        else:rows.append({'y':y(line),'members':[line]})
    output=[]
    for row in rows:
        members=sorted(row['members'],key=lambda line:line.box[0])
        words=[]
        for index,line in enumerate(members):
            if index and line.box[0]-members[index-1].box[2]>glyph*image.height/image.width*1.5:
                gap=[members[index-1].box[2],line.box[1],line.box[0],line.box[3]]
                words.append({'text':' ______ ','box':gap,'score':1})
            words.extend(line.words or [{'text':line.text,'box':line.box,'score':line.score}])
        output.append(replace(members[0],text=''.join(word['text'] for word in words),box=union([line.box for line in members]),words=words))
    return output


def fraction_lines(image,lines,figures):
    """Detect observed fraction bars with print on both sides of the rule."""
    import numpy as np
    import cv2
    if not lines:return lines
    glyph=statistics.median([line.text_height for line in lines if line.text_height and chinese(line.text)>=3] or [line.text_height for line in lines if line.text_height] or [.025])
    enhanced,_,_=document_cv.normalize_illumination(image)
    binary=(cv2.cvtColor(np.asarray(enhanced),cv2.COLOR_RGB2GRAY)<165).astype('uint8')*255
    used=set();extra=[]
    for i,numerator in enumerate(lines):
        if i in used or len(numerator.text)>18 or re.search(r'[=→⇌：:，。]',numerator.text):continue
        for j,denominator in enumerate(lines):
            if j in used or j==i or len(denominator.text)>20 or re.search(r'[=→⇌：:，。]',denominator.text):continue
            a,b=numerator.box,denominator.box
            gap=(b[1]+b[3]-a[1]-a[3])/2
            if not glyph*.45<gap<glyph*1.9:continue
            intersection=min(a[2],b[2])-max(a[0],b[0])
            if intersection<min(a[2]-a[0],b[2]-b[0])*.65:continue
            box=union([a,b]);l,t,r,bot=[round(value*scale) for value,scale in zip(box,[image.width,image.height,image.width,image.height])]
            if r-l>image.width*.4 or bot-t>glyph*image.height*3:continue
            segments=cv2.HoughLinesP(binary[t:bot,l:r],1,np.pi/180,threshold=max(8,round((r-l)*.25)),minLineLength=max(8,round((r-l)*.65)),maxLineGap=3)
            bar=any(abs(y1-y0)<max(3,(x1-x0)*.1) and (a[1]+a[3])*image.height/2-2<t+(y1+y0)/2<(b[1]+b[3])*image.height/2+2 for x0,y0,x1,y1 in (segments[:,0] if segments is not None else []))
            if not bar:continue
            word={'text':numerator.text+'/'+denominator.text,'box':box,'score':min(numerator.score,denominator.score),'fraction':True,
                  'numerator':numerator.text,'denominator':denominator.text}
            extra.append(replace(numerator,text=word['text'],box=box,words=[word],quad=None));used.update((i,j));break
    return [line for index,line in enumerate(lines) if index not in used]+extra


def math_candidate(text):
    text=text.strip(' \t(),.、;:（），。：；')
    if not text or re.fullmatch(r'[①②③④⑤⑥⑦⑧⑨⑩\d.]+|[ivIV]+|[A-H]',text):return False
    if re.fullmatch(r'[=+×÷<>()%\s]+',text):return False
    return bool(re.search(r'[A-Za-zΑ-ω][₀-₉0-9]|[₀-₉0-9][A-Za-zΑ-ω]|[=+÷×∑∫√Δ∆→⇌]|(?:ln|In)\s*k|[A-Za-z]_\{?|[A-Za-z0-9]/[A-Za-z0-9]',text))


def span_box(image,line,words):
    """Refine CTC character boundaries at observed ink gaps, never by chemistry."""
    import numpy as np
    import cv2
    selected=line.words;first=selected.index(words[0]);last=selected.index(words[-1])
    box=union([word['box'] for word in words]);height=(line.text_height or box[3]-box[1])*image.height
    centers=[(word['box'][0]+word['box'][2])*image.width/2 for word in selected]
    left=(centers[first-1]+centers[first])/2 if first else box[0]*image.width-height*.22
    right=(centers[last]+centers[last+1])/2 if last+1<len(selected) else box[2]*image.width+height*.22
    top=max(0,math.floor(box[1]*image.height-height*.12));bottom=min(image.height,math.ceil(box[3]*image.height+height*.12))
    normalized,_,_=document_cv.normalize_illumination(image.crop((0,top,image.width,bottom)))
    binary=cv2.cvtColor(np.asarray(normalized),cv2.COLOR_RGB2GRAY)<175
    counts=binary.sum(axis=0)
    radius=max(2,round(height*.16))
    def gap(target):
        lo=max(0,round(target)-radius);hi=min(image.width,round(target)+radius+1)
        if hi<=lo:return max(0,min(image.width,round(target)))
        indices=np.arange(lo,hi)
        # Ink-free gaps take priority; nearby gaps beat distant margins.
        costs=counts[lo:hi]*3+abs(indices-target)/max(1,radius)
        return int(indices[np.argmin(costs)])
    left=gap(left);right=gap(right)
    if any(word.get('fraction') or word.get('formula_extension') for word in words):
        left=min(left,max(0,math.floor(box[0]*image.width)-3));right=max(right,min(image.width,math.ceil(box[2]*image.width)+3))
    if right<=left:return box
    return [left/image.width,top/image.height,right/image.width,bottom/image.height]


def crop_views(image,box):
    l,t,r,b=box
    crop=image.crop((max(0,math.floor(l*image.width)),max(0,math.floor(t*image.height)),min(image.width,math.ceil(r*image.width)),min(image.height,math.ceil(b*image.height))))
    enhanced,_,_=document_cv.normalize_illumination(crop)
    return crop,enhanced


def figures_for(lines,elements):
    figures=[dict(element) for element in elements if element['label'] in GRAPHICS]
    # Grid detector includes axis annotations; the nearby explanatory fraction
    # above the grid remains text and must not be swallowed by its padding.
    for figure in figures:
        if figure.get('grid_box'):
            above=[line.box[3] for line in lines if chinese(line.text)>=4 and line.box[1]<figure['grid_box'][1] and line.box[3]>figure['box'][1] and line.box[3]<figure['grid_box'][1]+.02]
            if above:figure['box'][1]=max(figure['box'][1],max(above)+.002)
    groups=[]
    for figure in sorted(figures,key=lambda item:(item['box'][1],item['box'][0])):
        box=figure['box']
        group=next((group for group in groups if min(group['box'][3],box[3])-max(group['box'][1],box[1])>min(group['box'][3]-group['box'][1],box[3]-box[1])*.45),None)
        if group:group['box']=union([group['box'],box])
        else:groups.append({'box':list(box),'label':'原题示意图','kind':'diagram'})
    # OCR-only labels on the edge of a figure, e.g. 甲/乙, belong to that figure.
    for group in groups:
        labels=[line.box for line in lines if re.fullmatch(r'[甲乙丙丁]',line.text) and group['box'][0]-.02<line.box[0]<group['box'][2]+.02 and -.01<line.box[1]-group['box'][3]<.025]
        if labels:group['box']=union([group['box']]+labels)
    return groups


def transcribe(image,lines,elements,base,threshold=.985):
    """Replace only ordinary stem OCR; choice matching keeps its existing path."""
    if base.get('options') and all(re.fullmatch(r'\[[A-H]\]',option) for option in base['options']):return None
    if not any(line.words for line in lines):return None
    started=time.perf_counter()
    figures=figures_for(lines,elements)
    visible=[line for line in lines if not any(enclosed(line.box,fig['box'],.015) for fig in figures)]
    reactions=[line for line in visible if re.match(r'^[①②③④⑤⑥⑦⑧⑨]',line.text) and math_candidate(line.text)]
    if len(reactions)>=2:
        # OCR can omit a small stacked coefficient and everything after an
        # arrow. Preserve the observed neighboring reaction-column width even
        # when that tail has no OCR box; never stop a source crop at the arrow.
        extent=max(line.box[2] for line in reactions)
        expanded=[]
        for line in visible:
            if line in reactions and re.search(r'[→⇒⇌]\s*$',line.text) and line.box[2]<extent:
                box=[line.box[2],line.box[1],extent,line.box[3]]
                words=[*(line.words or []),{'text':'','box':box,'score':0,'formula_extension':True}]
                line=replace(line,box=union([line.box,box]),words=words,quad=None)
            expanded.append(line)
        visible=expanded
    visible=fraction_lines(image,visible,figures)
    visible=combine_rows(visible,image)
    glyph=statistics.median([line.text_height for line in visible if line.text_height and chinese(line.text)>=3] or [.025])
    regions=[];audit=[];events=[];calls=0;unavailable=''

    def formula(box,source,words):
        nonlocal calls,unavailable
        if unavailable:
            results=[];okay=False;reason=unavailable
        elif calls>=40:
            results=[];okay=False;reason='本页公式数量较多，超出自动转录预算'
        else:
            try:
                # These are small math atoms, not full pages. Repetitive model
                # output must stop promptly and retain its source crop.
                results=[local_document_ocr.recognize(view,'formula',192) for view in crop_views(image,box)]
                calls+=1;okay,reason=accepted(results,threshold,source,words)
                literal=chemical_atom(source,words,results,threshold)
                if literal is not None:
                    # Only literal source characters are typeset; neighboring
                    # text from the model never becomes part of the question.
                    okay=True;reason='';results[0]={**results[0],'text':literal}
            except Exception as error:
                # An unavailable local helper must never cause missing question
                # content or an implicit paid-provider fallback.
                unavailable='本地公式转录暂不可用：'+str(error)[:120]
                results=[];okay=False;reason=unavailable
        item={'box':box,'source':source,'accepted':okay,'reason':reason,'latex':canonical(results[0]['text']) if results else '',
              'views':[{'mean_probability':result.get('mean_probability'),'weak_tokens':critical_weak_tokens(result),'seconds':result.get('seconds'),'cached':result.get('cached')} for result in results]}
        audit.append(item)
        if okay:return '$'+item['latex']+'$'
        key=str(len(regions)+1)
        regions.append({'key':key,'kind':'formula','box':box,'line_height':glyph,'placement':'inline','label':'未通过复核的原图公式'})
        return f'[[图块:{key}]]'

    for line in visible:
        words=line.words
        if not words or line.text.startswith('$'):
            events.append(replace(line,text=line.text));continue
        pieces=[];run=[]
        from app.modules.learning.local_ocr import OPTION
        option=OPTION.match(line.text)
        if option and base.get('options'):
            pieces.append('['+option[1]+'] ')
            consumed=0;remaining=[]
            for word in words:
                consumed+=len(word['text'])
                if consumed>option.start(2):remaining.append(word)
            words=remaining
        def flush():
            if not run:return
            # Keep explanatory brackets outside the formula. A trailing '(E0'
            # starts a prose definition, whereas '(g)' stays inside chemistry.
            opens=[i for i,word in enumerate(run) if word['text'] in ('(', '（')]
            if opens and not any(word['text'] in (')','）') for word in run[opens[-1]+1:]):
                index=opens[-1];tail=run[index:];del run[index:]
                flush();pieces.append(tail[0]['text']);run.extend(tail[1:]);flush();return
            if run and run[-1]['text'] in (')','）') and sum(word['text'] in (')','）') for word in run)>sum(word['text'] in ('(','（') for word in run):
                closing=run.pop();flush();pieces.append(closing['text']);return
            text=''.join(word['text'] for word in run)
            if math_candidate(text):
                box=span_box(image,line,run)
                pieces.append(formula(box,text,run))
            else:pieces.append(text)
            run.clear()
        for word in words:
            char=word['text']
            if word.get('fraction') and CHINESE.search(char):
                flush();pieces.append(formula(span_box(image,line,[word]),char,[word]))
            elif word.get('fraction'):run.append(word)
            elif CHINESE.search(char) or any(c in DELIMITERS for c in char) or re.fullmatch(r'[①②③④⑤⑥⑦⑧⑨⑩]|\s*_+\s*',char):flush();pieces.append(char)
            else:run.append(word)
        flush()
        events.append(replace(line,text=''.join(pieces)))

    # Physical rows sharing a baseline are read left-to-right. Use true glyph
    # height, not the inflated bounding rectangle of a photographed sloping row.
    angle=document_cv.printed_angle(visible,image.size)
    slope=math.tan(math.radians(angle))*image.width/image.height
    def center(line):return (line.box[1]+line.box[3])/2-slope*(line.box[0]+line.box[2])/2
    rows=[]
    for line in sorted(events,key=lambda line:(center(line),line.box[0])):
        row=next((row for row in reversed(rows[-3:]) if abs(center(line)-row['y'])<glyph*.48),None)
        if row:row['members'].append(line)
        else:rows.append({'y':center(line),'members':[line]})
    assembled=[]
    for row in rows:
        members=sorted(row['members'],key=lambda line:line.box[0]);text=''
        for member in members:
            if text:
                previous=next((m for m in reversed(members[:members.index(member)]) if m.text),None)
                if previous and member.box[0]-previous.box[2]>glyph*image.height/image.width*1.3:text+=' ______ '
            text+=member.text
        assembled.append(replace(members[0],text=text,box=union([line.box for line in members])))
    for figure in figures:
        key=str(len(regions)+1)
        regions.append({**figure,'key':key,'line_height':glyph,'placement':'block'})
        assembled.append(replace(visible[0] if visible else lines[0],text=f'[[图块:{key}]]',box=figure['box']))
    assembled.sort(key=lambda line:(line.box[1],line.box[0]))
    stem=paragraphs(assembled)
    options=[]
    if base.get('options'):
        labels=list(re.finditer(r'(?m)^\s*\[([A-H])\]\s*',stem))
        expected=[match[1] for option in base['options'] if (match:=re.match(r'\[([A-H])\]',option))]
        if [match[1] for match in labels]!=expected:return None
        options=[stem[match.start():labels[index+1].start() if index+1<len(labels) else len(stem)].strip() for index,match in enumerate(labels)]
        stem=stem[:labels[0].start()].strip()
    passed=sum(item['accepted'] for item in audit)
    return {'stem':stem,'options':options,'inline_regions':regions,'formula_audit':audit,'has_diagram':bool(figures),
            'diagram_regions':[{'box':figure['box'],'label':figure['label']} for figure in figures],
            'structured_info':{'formula_count':len(audit),'accepted':passed,'fallback':len(audit)-passed,'threshold':threshold,'seconds':round(time.perf_counter()-started,2),'external_api_calls':0},
            'concerns':[f'本地公式分块复核：{passed}/{len(audit)}块通过双视图和高置信门槛，其余小块保留原位图像；概率不是准确率，入库前仍须校对'] if audit else []}
