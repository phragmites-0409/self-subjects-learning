"""Recover paragraphs from physical OCR rows without joining question parts."""
import re
import statistics

START=re.compile(r'^\s*(?:[（(]\d+[）)]|[①②③④⑤⑥⑦⑧⑨⑩]|第[①②③④⑤⑥⑦⑧⑨⑩\d]+步|[\[（(]?[A-H][\]）).、．]|\d+[、．.](?!\d)|反应(?:[ivIVⅠⅡⅢⅣ]+)?[（(]|已知|(?:题目|求证|证明)[：:])')

def join_text(left,right):
    if not left:return right.strip()
    if not right:return left.strip()
    space=' ' if re.search(r'[A-Za-z0-9]$',left) and re.match(r'[A-Za-z0-9]',right) else ''
    return left.rstrip()+space+right.lstrip()

def paragraphs(lines):
    if not lines:return ''
    heights=[line.box[3]-line.box[1] for line in lines]
    height=statistics.median(heights)
    result=[];previous=None
    for line in lines:
        text=line.text.strip()
        if not text:continue
        separate=bool(START.match(text) or text.startswith(('$$',r'\[','[[图块:')))
        if previous:
            gap=line.box[1]-previous.box[3]
            separate=separate or gap>height*.85 or previous.text.strip().endswith(('$$',r'\]', '[[图块:'))
            separate=separate or bool(re.fullmatch(r'\[\[图块:\d+\]\]',previous.text.strip()))
            separate=separate or previous.text.rstrip().endswith(('：',':'))
            separate=separate or (line.box[0]-previous.box[0]>.04 and previous.text.rstrip().endswith(('。','？','！','：',':')))
        if not result or separate:result.append(text)
        else:result[-1]=join_text(result[-1],text)
        previous=line
    return '\n\n'.join(result)
