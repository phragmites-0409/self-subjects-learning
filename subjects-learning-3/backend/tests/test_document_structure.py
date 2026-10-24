from io import BytesIO
from PIL import Image,ImageDraw
import pytest

from app.modules.learning.document_structure import detect_grids,grid_content,render_plain_array
from app.modules.learning.local_ocr import Line
from app.modules.learning.note_filter import apply,within_page
from app.modules.learning import ai
from app.modules.learning.local_ocr import reliable_formula
from app.modules.learning.local_ocr import question_from_lines
from app.modules.learning.printed_text_filter import filter_notes


def test_table_cells_preserve_rows_numbers_and_render_for_printing():
    grid={"x":[0,100,200],"y":[0,50,100],"box":[0,0,1,1]}
    lines=[Line("温度",[.1,.1,.3,.3]),Line("浓度",[.6,.1,.8,.3]),Line("20",[.1,.6,.3,.8]),Line("0.5",[.6,.6,.8,.8])]
    element,formula=grid_content(lines,grid,(200,100))
    assert element["label"]=="table_transcribed" and "0.5" in formula and "20" in formula
    image=Image.open(BytesIO(render_plain_array(formula)))
    assert image.width>=200 and image.height>=100
    from app.modules.learning.pdf import formatted
    from app.storage.local_store import LocalFilesystemContentStore
    markup=formatted(f"${formula}$",LocalFilesystemContentStore())
    assert markup.startswith('<img src=') and r"\begin{array}" not in markup


def test_sparse_plotted_grid_stays_a_complete_figure_without_axis_text_in_prose():
    image=Image.new("RGB",(600,500),"white");draw=ImageDraw.Draw(image)
    for x in range(100,501,100):draw.line((x,100,x,400),fill="black",width=2)
    for y in range(100,401,50):draw.line((100,y,500,y),fill="black",width=2)
    grids=detect_grids(image)
    assert len(grids)==1
    element,formula=grid_content([Line("95",[.08,.2,.15,.25])],grids[0],image.size)
    assert element["label"]=="chart" and formula is None
    assert element["box"][0]<100/600 and element["box"][3]>.8


def test_explicit_black_note_masks_change_only_selected_pixels_and_map_across_pages():
    image=Image.new("RGB",(100,100),"black")
    masked=apply(image,[[.5,.5,.8,.8]])
    assert masked.getpixel((60,60))==(255,255,255) and masked.getpixel((10,10))==(0,0,0)
    assert image.getpixel((60,60))==(0,0,0)
    assert within_page([[0,.6,1,.8]],[0,.5,1,1])[0]==pytest.approx([0,.2,1,.6])


def test_saved_note_filter_uses_review_draft_and_keeps_manual_answers(client,monkeypatch,png_bytes):
    monkeypatch.setattr(ai,"recognition_available",lambda db:True)
    seen=[]
    async def recognize(db,aid,text,excluded_boxes=None):
        seen.append(excluded_boxes)
        return ai.Recognition(stem="仅保留印刷题干",subject="数学")
    monkeypatch.setattr(ai,"recognize",recognize)
    uploaded=client.post("/api/v1/assets",files={"file":("q.png",png_bytes,"image/png")}).json()
    qid=uploaded["question_id"]
    client.post("/api/v1/learning/intake",json={"question_id":qid,"subject":"数学"})
    client.post(f"/api/v1/learning/questions/{qid}/answer",json={"answer":"1"})
    q=client.get(f"/api/v1/learning/questions/{qid}").json();version=q["version_id"]
    result=client.post(f"/api/v1/learning/questions/{qid}/notes/filter",json={"version_id":version,"page_index":0,"boxes":[[.5,.5,.8,.8]]})
    assert result.status_code==200,result.text
    q=client.get(f"/api/v1/learning/questions/{qid}").json()
    assert q["version_id"]==version and q["answer"]=="1" and q["answer_confirmed"]
    assert seen[-1]==[[.5,.5,.8,.8]] and q["data"]["recognition"]=="review"
    assert q["data"]["recognition_draft"]["stem"]=="仅保留印刷题干"
    adopted=client.post(f"/api/v1/learning/questions/{qid}/recognition/use-draft")
    assert adopted.status_code==200 and adopted.json()["answer"]=="1"


def test_note_filter_rejects_wrong_page_and_stale_version(client,monkeypatch,png_bytes):
    monkeypatch.setattr(ai,"recognition_available",lambda db:False)
    uploaded=client.post("/api/v1/assets",files={"file":("q.png",png_bytes,"image/png")}).json()
    qid=uploaded["question_id"];q=client.get(f"/api/v1/learning/questions/{qid}").json()
    assert client.post(f"/api/v1/learning/questions/{qid}/notes/filter",json={"version_id":"old","boxes":[]}).status_code==409
    assert client.post(f"/api/v1/learning/questions/{qid}/notes/filter",json={"version_id":q["version_id"],"page_index":1,"boxes":[]}).status_code==422


def test_margin_calculation_exclusion_never_uses_formula_size_as_handwriting_evidence():
    anchors=[Line("这是印刷题目的正文条件",[.1,y,.6,y+.02]) for y in [.1,.2,.3]]
    margin=Line("2x+3=7",[.72,.2,.94,.23])
    displayed=Line("E=mc2",[.2,.5,.6,.6])
    retained,notes=filter_notes(anchors+[margin,displayed],[])
    assert margin not in retained and len(notes)==1
    assert displayed in retained
    protected,_=filter_notes(anchors+[margin],[{"label":"formula","box":[.7,.18,.96,.25]}])
    assert margin in protected


def test_formula_guard_rejects_runaway_generation_without_rejecting_normal_fractions():
    assert reliable_formula(r"\frac{1}{2}O_2+H_2\rightarrow H_2O")
    assert not reliable_formula(r"\underbrace{x}"*20)
    assert not reliable_formula(r"\frac{1}{2")


def test_chart_padding_does_not_swallow_a_condition_that_extends_outside_the_crop():
    condition=Line("氢气与丙烷的比例变化如图乙所示",[.03,.3,.9,.33])
    axis=Line("0.5",[.45,.52,.48,.55])
    result=question_from_lines([condition,axis],[{"label":"chart","box":[.28,.29,.82,.6]}])
    assert condition.text in result["stem"] and "0.5" not in result["stem"]


def test_detached_hydrogen_symbol_is_not_an_eight_choice_question():
    result=question_from_lines([Line("热化学反应方程式",[.1,.1,.8,.15]),Line("H.(g)",[.6,.7,.8,.75])],[])
    assert result["options"]==[] and "H.(g)" in result["stem"]


def test_external_recognition_receives_the_same_explicit_note_mask(db,monkeypatch):
    import asyncio
    monkeypatch.setattr(ai,"recognition_configuration",lambda db:{"mode":"api"})
    original=Image.new("RGB",(100,100),"black");buf=BytesIO();original.save(buf,"PNG")
    monkeypatch.setattr(ai,"image_for",lambda *args:buf.getvalue())
    seen=[]
    async def generate(*args,**kwargs):
        seen.append(kwargs["image_override"])
        return ai.Recognition(stem="原题")
    monkeypatch.setattr(ai,"generate",generate)
    asyncio.run(ai.recognize(db,"photo","",[[.5,.5,.8,.8]]))
    masked=Image.open(BytesIO(seen[0]))
    assert masked.getpixel((60,60))==(255,255,255)
    assert masked.getpixel((10,10))==(0,0,0)
