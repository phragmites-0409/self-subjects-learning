from io import BytesIO
import hashlib
import subprocess
import pytest
from PIL import Image, ImageDraw, ImageChops
from app.modules.learning.diagram_processing import pencil_cleanup, erase_strokes
from app.modules.learning import ai, imaging, service
from app.modules.learning.models import QuestionState
from app.modules.learning.pdf import export_pdf
from sqlalchemy import select
from app.modules.learning.models import LearningEvent
from pypdf import PdfReader


@pytest.mark.parametrize("failure", ["timeout", "missing_executable"])
def test_pdf_retains_formula_when_renderer_is_unavailable(monkeypatch, db, question_factory, failure):
    from app.modules.learning import formula_rendering

    formula_rendering.render.cache_clear()
    monkeypatch.setattr(formula_rendering, "ready", lambda: True)

    def unavailable(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("node", 15)
        raise FileNotFoundError("node unavailable")

    monkeypatch.setattr(formula_rendering.subprocess, "run", unavailable)
    q, _ = question_factory(stem=r"条件 $x_{render_failure}$，请计算。")
    state = service.state_for(db, q.id)
    review = service.make_round(db, "error", "数学", service.today(), service.today(), [state])
    db.commit()
    event = db.scalar(select(LearningEvent).where(LearningEvent.data["round_id"].as_string() == review.id))
    reader = PdfReader(export_pdf(db, event.id))
    assert len(reader.pages) == 1
    # A failed external renderer may use the local raster fallback. Both retain the formula.
    assert "$x_{render_failure}$" in reader.pages[0].extract_text() or len(reader.pages[0].images) == 1


def test_gray_pencil_attenuates_but_dark_print_and_original_survive():
    original = Image.new("RGB", (320, 160), (225, 225, 225))
    draw = ImageDraw.Draw(original)
    draw.line((20, 100, 300, 100), fill=(20, 20, 20), width=2)
    draw.line((20, 40, 300, 40), fill=(175, 175, 175), width=2)
    before = original.tobytes()
    clean, info = pencil_cleanup(original, "balanced")
    assert clean.getpixel((100, 40))[0] > 235
    assert clean.getpixel((100, 100))[0] < 50
    assert original.tobytes() == before
    assert info["image_review_required"] and info["pencil_changed_pixels"] > 0
    assert pencil_cleanup(original, "off")[0].tobytes() == before


def test_local_mask_only_touches_requested_region_and_rejects_bad_coordinates():
    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image); draw.line((0, 80, 199, 80), fill="black", width=2)
    draw.line((25, 25, 60, 25), fill="gray", width=2)
    cleaned, mask = erase_strokes(image, [{"points": [[.125, .25], [.3, .25]], "radius": .015}])
    assert cleaned.getpixel((40, 25)) == (255, 255, 255)
    assert cleaned.getpixel((40, 80)) == image.getpixel((40, 80))
    assert ImageChops.difference(cleaned, image).getbbox() is not None
    with pytest.raises(Exception):
        erase_strokes(image, [{"points": [[float("nan"), .3]], "radius": .01}])


def test_crop_uses_cleaned_copy_undo_and_confirmation_are_question_owned(client, db, question_factory):
    q, _ = question_factory()
    original = Image.new("RGB", (120, 100), "white")
    clean = Image.new("RGB", (120, 100), (250, 250, 250))
    q.source_asset_id = imaging.store_image(db, original)
    state = service.state_for(db, q.id)
    state.data = {"processed_asset_id": imaging.store_image(db, clean)}
    db.commit()
    response = client.post(f"/api/v1/learning/questions/{q.id}/crop", json={"left": .1, "top": .1, "right": .7, "bottom": .7})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    result = imaging.load_image(db, data["crop_asset_id"])
    assert result.getpixel((1, 1)) == (250, 250, 250)
    assert data["image_review_required"]
    assert client.post(f"/api/v1/learning/questions/{q.id}/image/confirm").json()["data"]["image_review_required"] is False
    other = imaging.store_image(db, Image.new("RGB", (20,20), "red")); db.commit()
    assert client.post(f"/api/v1/learning/questions/{q.id}/image/erase", json={"asset_id": other, "strokes": [{"points": [[.1,.1]], "radius": .01}]}).status_code == 422
    restored = client.post(f"/api/v1/learning/questions/{q.id}/image/undo").json()["data"]
    assert restored["processed_asset_id"] == state.data["processed_asset_id"] and not restored.get("crop_asset_id")
    assert imaging.load_image(db, q.source_asset_id).tobytes() == original.tobytes()


def test_multi_crop_refuses_wrong_option_mapping(client, db, question_factory):
    q, _ = question_factory()
    q.source_asset_id = imaging.store_image(db, Image.new("RGB", (200,200), "white")); db.commit()
    from app.api.v1.learning import question_service
    question_service().update(db, q, {"content": {"stem":"选择图形", "options":["[A]","[B]"], "has_diagram":True}})
    wrong = client.post(f"/api/v1/learning/questions/{q.id}/image/crop", json={"boxes":[{"box":[0,0,.4,.4],"label":"A"}]})
    assert wrong.status_code == 422 and "全部图形选项" in wrong.text


def test_reprocess_text_only_question_clears_stale_crop_without_blocking_print(client, db, question_factory):
    q, _ = question_factory(stem="纯文字题，不包含示意图")
    q.source_asset_id = imaging.store_image(db, Image.new("RGB", (200, 120), "white"))
    state = service.state_for(db, q.id)
    old_crop = imaging.store_image(db, Image.new("RGB", (40, 40), "gray"))
    state.data = {"crop_asset_id": old_crop, "print_options_embedded": True, "image_review_required": True}
    db.commit()
    response = client.post(f"/api/v1/learning/questions/{q.id}/image/process", json={"pencil": "balanced"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["crop_asset_id"] is None and not data["print_options_embedded"] and not data["image_review_required"]
    assert data["image_history"][-1]["crop_asset_id"] == old_crop


def test_reprocessing_preserves_migrated_option_geometry_without_replacing_stem(client, db, question_factory):
    q, _ = question_factory(stem="人工校对的题干必须保留")
    from app.api.v1.learning import question_service
    question_service().update(db, q, {"content": {"stem":"人工校对的题干必须保留", "options":["[A]","[B]"], "has_diagram":True}})
    q.source_asset_id = imaging.store_image(db, Image.new("RGB", (200,200), "white"))
    state = service.state_for(db,q.id)
    state.data = {"image_geometry_version_id": q.current_version_id, "image_diagram_regions": [{"box":[0,0,.45,.45],"label":"A"},{"box":[.5,0,1,.45],"label":"B"}]}
    db.commit()
    response = client.post(f"/api/v1/learning/questions/{q.id}/image/process", json={"pencil":"gentle"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["print_options_embedded"]
    assert response.json()["content"]["stem"] == "人工校对的题干必须保留"


def test_inline_formulas_unicode_scripts_and_answer_space_export_single_page(db, question_factory):
    text = ('8.（2024·成都市高二期中）如图，一列简谐横波沿 $x$ 轴负方向传播，'
        '实线和虚线分别表示 $t_1=0$ 和 $t_2=0.75\\,s$ 时的波形图。'
        '若该波的周期 $T>0.75\\,s$，则 $t_3=1\\,s$ 时的波形图为。另核对 t₁ 和 x²。')
    q, _ = question_factory(stem=text)
    state = service.state_for(db, q.id)
    state.answer = "不得泄露的标准答案"
    state.data = {"crop_asset_id": imaging.store_image(db, Image.new("RGB", (600,650), "white"))}
    review = service.make_round(db, "error", "数学", service.today(), service.today(), [state]); db.commit()
    event = db.scalar(select(LearningEvent).where(LearningEvent.data["round_id"].as_string() == review.id))
    reader = PdfReader(export_pdf(db, event.id))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "不得泄露" not in text and "另核对" in text
    assert len(reader.pages[0].images) >= 4


def test_default_image_processing_keeps_faint_printed_diagram(db):
    original = Image.new('RGB',(320,200),'white')
    draw = ImageDraw.Draw(original)
    draw.line((30,100,200,100),fill=(190,190,190),width=2)
    aid = imaging.store_image(db,original)
    output = ai.Recognition(stem='含虚线的题',has_diagram=True,diagram_regions=[ai.ImageRegion(box=[.05,.35,.7,.7])])
    data = imaging.process_question(db,aid,output,pencil='balanced')
    image = imaging.load_image(db,data['processed_asset_id'])
    assert image.getpixel((100,100))[0] < 220
    assert data['image_review_required']
    assert any('浅色' in note for note in data['image_processing_concerns'])


def test_cleaned_page_ocr_is_reviewed_before_adoption_and_keeps_human_answer(client,db,question_factory,monkeypatch):
    q, _ = question_factory(stem='人工旧题干')
    q.source_asset_id = imaging.store_image(db,Image.new('RGB',(120,100),'white'))
    state = service.state_for(db,q.id)
    state.answer = '人工答案B'
    state.answer_confirmed = True
    processed_id = imaging.store_image(db,Image.new('RGB',(120,100),(245,245,245)))
    state.data = {'processed_asset_id':processed_id,'answer_explanation':'人工解析','intake_complete':True}
    db.commit()
    seen = []
    async def recognize(_db,aid,hint):
        seen.append(aid)
        return ai.Recognition(stem='新提取的印刷题干',options=['[A] 一','[B] 二'])
    monkeypatch.setattr(ai,'recognize',recognize)
    monkeypatch.setattr(ai,'recognition_available',lambda db: True)
    prefix = f'/api/v1/learning/questions/{q.id}'
    assert client.post(prefix+'/recognize',json={'source':'processed'}).status_code == 200
    data = client.get(prefix).json()
    assert seen == [processed_id]
    assert data['content']['stem'] == '人工旧题干'
    assert data['data']['recognition'] == 'review'
    assert data['answer'] == '人工答案B' and data['answer_confirmed']
    adopted = client.post(prefix+'/recognition/use-draft')
    assert adopted.status_code == 200,adopted.text
    data = adopted.json()
    assert data['content']['stem'] == '新提取的印刷题干'
    assert data['answer'] == '人工答案B' and data['answer_confirmed']
    assert data['data']['answer_explanation'] == '人工解析'
    assert data['source_asset_id'] == q.source_asset_id


def test_recognition_draft_cannot_overwrite_a_later_edit(client,db,question_factory):
    q, _ = question_factory()
    q.source_asset_id = imaging.store_image(db,Image.new('RGB',(120,100),'white'))
    state = service.state_for(db,q.id)
    state.data = {'recognition_draft':ai.Recognition(stem='过期草稿').model_dump(),
        'recognition_draft_version':q.current_version_id,'recognition_draft_source':q.source_asset_id}
    db.commit()
    from app.api.v1.learning import question_service
    question_service().update(db,q,{'content':{'stem':'刚刚人工修改的题干'}})
    db.commit()
    response = client.post(f'/api/v1/learning/questions/{q.id}/recognition/use-draft')
    assert response.status_code == 409
    assert client.get(f'/api/v1/learning/questions/{q.id}').json()['content']['stem'] == '刚刚人工修改的题干'


def test_protection_brush_keeps_curve_pixels_inside_erased_area():
    image=Image.new('RGB',(200,100),'white')
    draw=ImageDraw.Draw(image)
    draw.line((20,50,180,50),fill='black',width=2)
    draw.line((100,20,100,80),fill='gray',width=2)
    clean,mask=erase_strokes(image,[{'points':[[.5,.2],[.5,.8]],'radius':.02}],
        'inpaint',[{'points':[[.1,.5],[.9,.5]],'radius':.01}])
    assert clean.getpixel((100,50))==image.getpixel((100,50))
    assert mask.getpixel((100,50))==0
    assert clean.getpixel((100,30))!=image.getpixel((100,30))


def test_preview_does_not_change_print_and_adoption_is_owned_undoable(client,db,question_factory):
    q,_=question_factory()
    image=Image.new('RGB',(200,100),'white')
    ImageDraw.Draw(image).line((30,20,100,20),fill='gray',width=3)
    q.source_asset_id=imaging.store_image(db,image)
    state=service.state_for(db,q.id)
    state.answer='人工答案'
    state.answer_confirmed=True
    state.data={'crop_asset_id':q.source_asset_id,'image_review_required':False}
    db.commit()
    prefix=f'/api/v1/learning/questions/{q.id}/image'
    preview=client.post(prefix+'/repair-preview',json={'asset_id':q.source_asset_id,
        'method':'inpaint','strokes':[{'points':[[.15,.2],[.5,.2]],'radius':.02}]})
    assert preview.status_code==200,preview.text
    data=preview.json()['data']; candidate=data['image_repair_draft']['asset_id']
    assert data['crop_asset_id']==q.source_asset_id and not data['image_review_required']
    assert client.post(prefix+'/repair-adopt',json={'asset_id':q.source_asset_id}).status_code==422
    adopted=client.post(prefix+'/repair-adopt',json={'asset_id':candidate})
    assert adopted.status_code==200,adopted.text
    assert adopted.json()['data']['image_review_required']
    assert adopted.json()['answer']=='人工答案' and adopted.json()['answer_confirmed']
    assert client.post(prefix+'/undo').json()['data']['crop_asset_id']==q.source_asset_id
    assert imaging.load_image(db,q.source_asset_id).tobytes()==image.tobytes()


def test_local_model_composite_changes_only_explicit_mask(monkeypatch):
    import numpy as np
    from app.modules.learning import diagram_repair
    image=Image.new('RGB',(640,400),(220,218,210))
    mask=Image.new('L',image.size,0)
    ImageDraw.Draw(mask).rectangle((250,150,260,180),fill=255)
    class FakeSession:
        def run(self,outputs,feeds):
            assert feeds['image'].shape==(1,3,512,512)
            assert feeds['mask'].shape==(1,1,512,512)
            return [np.full((1,3,512,512),255.,np.float32)]
    monkeypatch.setattr(diagram_repair,'configuration',lambda:{'model':'local','sha256':'tested'})
    monkeypatch.setattr(diagram_repair,'session',lambda *args:FakeSession())
    clean=diagram_repair.repair(image,mask)
    changed=np.any(np.asarray(clean)!=np.asarray(image),axis=2)
    assert not changed[np.asarray(mask)==0].any()
    assert clean.getpixel((255,165))==(255,255,255)
    assert image.getpixel((255,165))==(220,218,210)


def test_stale_preview_cannot_replace_later_crop(client,db,question_factory):
    q,_=question_factory()
    q.source_asset_id=imaging.store_image(db,Image.new('RGB',(200,100),'white'))
    old=imaging.store_image(db,Image.new('RGB',(100,100),'gray'))
    new=imaging.store_image(db,Image.new('RGB',(100,100),'black'))
    state=service.state_for(db,q.id)
    state.data={'crop_asset_id':new,'image_repair_draft':{'asset_id':old,'source_asset_id':old,'version_id':q.current_version_id}}
    db.commit()
    response=client.post(f'/api/v1/learning/questions/{q.id}/image/repair-adopt',json={'asset_id':old})
    assert response.status_code==422
    assert client.get(f'/api/v1/learning/questions/{q.id}').json()['data']['crop_asset_id']==new
