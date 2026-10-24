import numpy as np
import pytest
from PIL import Image
from app.core.errors import AppError
from app.modules.learning import ink_segmentation as ink
from app.modules.learning.diagram_processing import erase_strokes,stroke_mask

@pytest.fixture
def model(monkeypatch):
    class Engine:
        def run(self,*args):return [np.full((1,1,1024,1024),10,np.float32)]
    monkeypatch.setattr(ink,'configuration',lambda:{'onnx_file':'test','onnx_sha256':'test'})
    monkeypatch.setattr(ink,'engine',lambda *args:Engine())

def test_pixel_classifier_can_never_expand_beyond_user_brush_or_blue_protection(model):
    image=Image.new('RGB',(100,100),'black')
    strokes=[{'points':[[.5,.5]],'radius':.05}]
    protect=[{'points':[[.51,.5]],'radius':.01}]
    clean,mask=erase_strokes(image,strokes,'handwriting',protect)
    selected=np.asarray(mask)>0
    allowed=np.asarray(stroke_mask(image,strokes))>0
    protected=np.asarray(stroke_mask(image,protect))>0
    assert selected.any() and not selected[~allowed].any() and not selected[protected].any()
    assert np.array_equal(np.asarray(clean)[~selected],np.asarray(image)[~selected])

def test_uncertain_model_does_not_apply_fallback_erasure(monkeypatch,model):
    class Empty:
        def run(self,*args):return [np.full((1,1,1024,1024),-10,np.float32)]
    monkeypatch.setattr(ink,'engine',lambda *args:Empty())
    with pytest.raises(AppError) as error:
        ink.refine(Image.new('RGB',(100,100),'white'),Image.new('L',(100,100),255))
    assert error.value.code=='NO_CONFIDENT_HANDWRITING'

def test_unavailable_model_has_no_download_or_silent_fallback(monkeypatch):
    monkeypatch.setattr(ink,'configuration',lambda:None)
    with pytest.raises(AppError) as error:
        ink.refine(Image.new('RGB',(100,100),'white'),Image.new('L',(100,100),255))
    assert error.value.code=='INK_MODEL_NOT_READY'

def test_full_page_erasure_is_rejected(model):
    with pytest.raises(AppError) as error:
        ink.refine(Image.new('RGB',(1500,1500),'white'),Image.new('L',(1500,1500),255))
    assert error.value.code=='INK_REGION_TOO_LARGE'

def test_handwriting_model_requires_preview_and_keeps_manual_answer(client,png_bytes,model):
    uploaded=client.post('/api/v1/assets',files={'file':('q.png',png_bytes,'image/png')}).json()
    qid=uploaded['question_id'];url=f'/api/v1/learning/questions/{qid}'
    client.post(url+'/answer',json={'answer':'人工确认答案'})
    before=client.get(url).json()
    body={'asset_id':before['source_asset_id'],'method':'handwriting','strokes':[{'points':[[.5,.5]],'radius':.05}]}
    assert client.post(url+'/image/erase',json=body).status_code==422
    response=client.post(url+'/image/repair-preview',json=body)
    assert response.status_code==200,response.text
    preview=response.json();assert preview['version_id']==before['version_id']
    assert preview['answer']=='人工确认答案' and preview['answer_confirmed']
    assert preview['data'].get('processed_asset_id')==before['data'].get('processed_asset_id')
    draft=preview['data']['image_repair_draft'];assert draft['method']=='handwriting'
    adopted=client.post(url+'/image/repair-adopt',json={'asset_id':draft['asset_id']})
    assert adopted.status_code==200 and adopted.json()['answer']=='人工确认答案'
    assert adopted.json()['data']['image_review_required']

def test_later_crop_cannot_be_replaced_by_an_earlier_original_image_preview(client,png_bytes,model):
    uploaded=client.post('/api/v1/assets',files={'file':('q.png',png_bytes,'image/png')}).json()
    url=f"/api/v1/learning/questions/{uploaded['question_id']}"
    q=client.get(url).json()
    preview=client.post(url+'/image/repair-preview',json={'asset_id':q['source_asset_id'],'method':'handwriting','strokes':[{'points':[[.5,.5]],'radius':.05}]}).json()
    draft=preview['data']['image_repair_draft']
    crop=client.post(url+'/image/crop',json={'asset_id':q['source_asset_id'],'boxes':[{'box':[.1,.1,.9,.9],'label':''}]}).json()
    rejected=client.post(url+'/image/repair-adopt',json={'asset_id':draft['asset_id']})
    assert rejected.status_code==409
    assert client.get(url).json()['data']['crop_asset_id']==crop['data']['crop_asset_id']
