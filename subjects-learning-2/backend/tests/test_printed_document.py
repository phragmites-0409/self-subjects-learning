from PIL import Image,ImageDraw
import numpy as np
import pytest
from sqlalchemy import select
from app.db.models import Asset
from app.modules.learning.local_ocr import Line
from app.modules.learning.printed_document import filter_printed,source_layout
from app.modules.learning.question_pages import merge_pages
from app.modules.learning import ai,imaging,service as flow
from app.modules.learning.models import RoundItem,LearningEvent
from app.modules.learning.pdf import export_pdf

def test_sloping_rows_use_character_height_not_the_tall_bounding_rectangle():
    from app.modules.learning.local_ocr import glyph_height
    quad=np.array([[0,0],[100,20],[100,30],[0,10]],np.float32)
    assert glyph_height(quad,100)==pytest.approx(.1)
    text,regions=source_layout([Line('热化学反应方程式',[0,0,1,.3],1,.1)],[])
    assert regions[0]['line_height']==pytest.approx(.1)

def test_semantic_handwriting_rejects_calculation_figure_and_text_but_keeps_print_and_chart():
    image=Image.new('RGB',(200,200),'white');draw=ImageDraw.Draw(image)
    draw.rectangle((20,20,170,35),fill='black');draw.rectangle((20,100,80,130),fill='black')
    probability=np.zeros((200,200),np.float32);probability[100:140,20:100]=1
    print_line=Line('这是印刷正文条件',[.1,.1,.85,.175]);note=Line('2x+3=7',[.1,.5,.4,.65])
    elements=[{'label':'figure','box':[.1,.5,.4,.65]},{'label':'chart','box':[.5,.5,.9,.9]}]
    lines,regions,messages=filter_printed(image,[print_line,note],elements,probability)
    assert lines==[print_line] and not any(r['label']=='figure' for r in regions)
    assert any(r['label']=='chart' for r in regions) and messages

def test_safe_erasure_rectangles_never_touch_kept_print():
    image=Image.new('RGB',(100,100),'black');probability=np.ones((100,100),np.float32)
    printed=Line('原题中的文字不得误擦',[.1,.1,.8,.3]);note=Line('3+2=5',[.1,.2,.4,.4])
    lines,regions,_=filter_printed(image,[printed,note],[],probability)
    assert printed in lines and note not in lines
    assert all(item['label']=='excluded_note' for item in regions)

def test_equations_group_in_place_and_separate_question_sections():
    lines=[Line('热化学反应方程式',[.1,.05,.9,.08]),Line('C3H8=CH4+C2H4',[.1,.11,.6,.14]),Line('H2+O2=H2O',[.1,.15,.6,.18]),Line('(3)反应条件如下',[.1,.21,.8,.24]),Line('计算结束',[.1,.7,.8,.73])]
    stem,regions=source_layout(lines,[{'label':'figure','box':[.2,.4,.8,.6]}])
    assert len(regions)==4 and regions[1]['kind']=='formula' and regions[3]['kind']=='diagram'
    assert stem.index('[[图块:2]]')<stem.index('[[图块:3]]')<stem.index('[[图块:4]]')<stem.index('计算结束')
    assert regions[1]['box'][1]<.11 and .18<regions[1]['box'][3]<.21

def test_inline_keys_do_not_collide_when_multiple_photos_are_merged():
    regions=[{'key':'1','kind':'formula','box':[.1,.1,.9,.2],'label':'原图公式'}]
    page={'stem':'前文\n[[图块:1]]\n后文','inline_regions':regions,'metadata':{'subject_text':'化学反应方程式'}}
    merged=merge_pages([page,page],[{'box':[0,0,1,.4]},{'box':[0,.5,1,1]}])
    assert merged['stem'].count('[[图块:1]]')==1 and merged['stem'].count('[[图块:2]]')==1
    assert merged['inline_regions'][1]['box']==pytest.approx([.1,.55,.9,.6])

def make_inline_question(client,db,png_bytes,monkeypatch):
    monkeypatch.setattr(ai,'recognition_available',lambda db:True)
    async def recognize(*args,**kwargs):
        return ai.Recognition(stem='前文\n[[图块:1]]\n后文',subject='化学',inline_regions=[{'key':'1','kind':'formula','label':'公式','box':[.1,.1,.9,.9]}])
    monkeypatch.setattr(ai,'recognize',recognize)
    uploaded=client.post('/api/v1/assets',files={'file':('q.png',png_bytes,'image/png')}).json()
    qid=uploaded['question_id'];client.post('/api/v1/learning/intake',json={'question_id':qid})
    return qid,client.get(f'/api/v1/learning/questions/{qid}').json()

def test_inline_edit_ownership_undo_confirmation_and_version_snapshot(client,db,png_bytes,monkeypatch):
    qid,q=make_inline_question(client,db,png_bytes,monkeypatch);url=f'/api/v1/learning/questions/{qid}'
    original=q['content']['inline_images'][0]['asset_id']
    assert q['data']['image_review_required']
    assert client.post(url+'/image/erase',json={'asset_id':'foreign','strokes':[]}).status_code==422
    edited=client.post(url+'/image/crop',json={'asset_id':original,'boxes':[{'box':[0,0,.8,.8]}]}).json()
    current=edited['data']['inline_images'][0]['asset_id'];assert current!=original
    assert client.post(url+'/image/confirm').json()['data']['image_confirmed_inline_ids']==[current]
    saved=client.patch(url,json={'content':{'stem':'新前文\n[[图块:1]]\n后文'}}).json()
    assert saved['content']['inline_images'][0]['asset_id']==current
    assert client.patch(url,json={'content':{'stem':'[[图块:99]]'}}).status_code==422
    assert client.post(url+'/image/undo').json()['data']['inline_images'][0]['asset_id']==original

def test_round_freezes_inline_images_and_pdf_renders_source_at_anchor(client,db,png_bytes,monkeypatch):
    import fitz
    qid,q=make_inline_question(client,db,png_bytes,monkeypatch)
    state=flow.state_for(db,qid);question=flow.get_question(db,qid)
    question.status='approved';state.data={**state.data,'image_review_required':False}
    initial=state.data['inline_images'][0]['asset_id']
    r=flow.make_round(db,'error','化学','2026-10-16','2026-10-16',[state]);db.commit()
    item=db.scalar(select(RoundItem).where(RoundItem.round_id==r.id));event=db.scalar(select(LearningEvent).where(LearningEvent.data['round_id'].as_string()==r.id))
    state.data={**state.data,'inline_images':[]};db.commit()
    assert item.data['inline_images'][0]['asset_id']==initial
    path=export_pdf(db,event.id)
    with fitz.open(path) as document:
        assert sum(len(page.get_images()) for page in document)==1
        assert '图块' not in ''.join(page.get_text() for page in document)


def test_cannot_restore_pre_layout_images_into_a_new_anchored_question(client,db,png_bytes,monkeypatch):
    qid,q=make_inline_question(client,db,png_bytes,monkeypatch)
    state=flow.state_for(db,qid);state.data={**state.data,'image_history':[{'inline_images':None}]};db.commit()
    response=client.post(f'/api/v1/learning/questions/{qid}/image/undo')
    assert response.status_code==409 and 'IMAGE_VERSION_MISMATCH' in response.text
