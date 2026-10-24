"""Conservative note proposals outside protected printed rows and figures."""
import re
import statistics


def overlap(a,b):return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]


def filter_notes(lines,elements):
    anchors=[line for line in lines if len(re.findall(r"[\u4e00-\u9fff]",line.text))>=5 and line.score>=.8 and not re.search(r"第\s*\d+\s*页.*共",line.text)]
    if len(anchors)<3:return lines,[]
    height=statistics.median(line.box[3]-line.box[1] for line in anchors)
    protected=[item["box"] for item in elements if item["label"] in ("figure","image","chart","table","formula","isolate_formula","isolated_formula","display_formula","equation")]
    protected += [[max(0,line.box[0]-.012),max(0,line.box[1]-.01),min(1,line.box[2]+.012),min(1,line.box[3]+.01)] for line in anchors]
    retained=[];notes=[]
    for line in lines:
        chinese=len(re.findall(r"[\u4e00-\u9fff]",line.text))
        if chinese>1 or line.text.startswith("$") or not re.search(r"[=+×]",line.text) or re.match(r"^[①②③④⑤⑥⑦⑧⑨]|^\([1-9]\)",line.text):
            retained.append(line);continue
        nearby=[anchor for anchor in anchors if abs((anchor.box[1]+anchor.box[3]-line.box[1]-line.box[3])/2)<height*1.8]
        outside_row=bool(nearby) and (line.box[0]>max(anchor.box[2] for anchor in nearby)+.025 or line.box[2]<min(anchor.box[0] for anchor in nearby)-.025)
        # A large standalone equation may be printed. Size alone is not evidence
        # of handwriting: only use a detached margin calculation beside body rows.
        if not outside_row or any(overlap(line.box,box) for box in protected):retained.append(line);continue
        box=[max(0,line.box[0]-.003),max(0,line.box[1]-.003),min(1,line.box[2]+.003),min(1,line.box[3]+.003)]
        if any(overlap(box,item) for item in protected):retained.append(line);continue
        notes.append({"label":"handwriting","box":box,"score":line.score,"source":"printed-row-geometry"})
    return retained,notes
