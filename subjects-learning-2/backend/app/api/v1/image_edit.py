"""Question-only image editing. Answer-photo handwriting is never erased here."""
import json
import re
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.modules.learning import ai, imaging, service as flow
from app.modules.learning.diagram_processing import diagram_sheet, erase_strokes

router = APIRouter(prefix="/learning")
IMAGE_FIELDS = ("processed_asset_id", "crop_asset_id", "diagram_asset_ids", "diagram_crop_fallback",
    "print_options_embedded", "diagram_layout", "image_review_required", "pencil_mode",
    "pencil_changed_pixels", "print_parts", "print_source_asset_id", "image_processing_concerns", "image_confirmed_asset_id",
    "image_diagram_regions", "image_geometry_version_id", "inline_images", "image_confirmed_inline_ids")


def view(db, qid):
    from app.api.v1.learning import question
    return question(qid, db=db)


def remember(state):
    state.data = {**state.data, "image_history": [*state.data.get("image_history", [])[-39:],
        {key: state.data.get(key) for key in IMAGE_FIELDS}]}


def checked_source(q, state, source):
    if state.data.get("recognition") in ("queued", "running"):
        flow.fail("请等待识别完成后再编辑图像", "IMAGE_BUSY", 409)
    allowed = {q.source_asset_id, state.data.get("processed_asset_id"), state.data.get("crop_asset_id")}
    allowed.update(item['asset_id'] for item in state.data.get('inline_images') or [])
    if not source or source not in allowed:
        flow.fail("只能编辑当前题目的原图、处理稿或打印图", "INVALID_IMAGE_SOURCE", 422)
    return source


@router.post("/questions/{qid}/image/process")
def process(qid: str, body: dict, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    state = flow.state_for(db, qid)
    if state.data.get("recognition") in ("queued", "running"):
        flow.fail("请等待识别完成后再编辑图像", "IMAGE_BUSY", 409)
    content = flow.question_content(db, q)
    if state.data.get("image_geometry_version_id") == q.current_version_id and state.data.get("image_diagram_regions") is not None:
        content = {**content, "diagram_regions": state.data["image_diagram_regions"]}
    recognition = ai.Recognition.model_validate({**content, "stem": content.get("stem", "")})
    config = ai.recognition_configuration(db)
    ink, pencil = body.get("ink", config["ink"]), body.get("pencil", config["pencil"])
    if ink not in {"off", "red", "red_blue"}:
        flow.fail("请选择有效的颜色处理方式", "INVALID_IMAGE_MODE", 422)
    from app.modules.learning.note_filter import boxes_for
    result = imaging.process_question(db, q.source_asset_id, recognition, ink, pencil, boxes_for(q,state))
    remember(state)
    state.data = {**state.data, **result, "print_parts": None, "print_source_asset_id": None,
        "image_diagram_regions": [r.model_dump() for r in recognition.diagram_regions], "image_geometry_version_id": q.current_version_id}
    db.commit()
    return view(db, qid)


def crop(qid, body, db):
    q = flow.get_question(db, qid)
    state = flow.state_for(db, qid)
    source = checked_source(q, state, body.get("asset_id") or state.data.get("processed_asset_id") or q.source_asset_id)
    image = imaging.load_image(db, source)
    boxes = body.get("boxes")
    if boxes is None:
        boxes = [{"box": [body.get(k) for k in ("left", "top", "right", "bottom")], "label": ""}]
    if not isinstance(boxes, list) or not 1 <= len(boxes) <= 12:
        flow.fail("请选择 1 至 12 个完整图块", "INVALID_BOX", 422)
    parts, validated, labels = [], [], []
    for item in boxes:
        if not isinstance(item, dict):
            flow.fail("裁图格式无效", "INVALID_BOX", 422)
        box, label = item.get("box"), item.get("label", "")
        if not isinstance(box, list) or len(box) != 4 or not isinstance(label, str) or label not in ("", *"ABCDEFGH"):
            flow.fail("请选择主图或有效选项编号", "INVALID_BOX", 422)
        coordinates = imaging.bounds(box, *image.size)
        if coordinates[2]-coordinates[0] < 10 or coordinates[3]-coordinates[1] < 10:
            flow.fail("裁图区域过小", "INVALID_BOX", 422)
        if label:
            labels.append(label)
        parts.append((label, image.crop(coordinates)))
        validated.append({"box": box, "label": label})
    expected = [re.search(r"[A-H]", s).group() for s in flow.question_content(db, q).get("options", []) if re.fullmatch(r"\s*\[[A-H]\]\s*", s)]
    if len(set(labels)) != len(labels) or (labels and sorted(labels) != sorted(expected)):
        flow.fail("选项图编号必须唯一，并与题目的全部图形选项对应", "OPTION_IMAGE_MISMATCH", 422)
    result = parts[0][1] if len(parts) == 1 and not labels else diagram_sheet(parts)
    if any(item['asset_id']==source for item in state.data.get('inline_images') or []):
        if len(parts)!=1 or labels:
            flow.fail('原位公式或题图每次裁切一个无编号图块','INVALID_BOX',422)
        save_erasure(db,q,state,source,result)
        db.commit()
        return view(db,qid)
    remember(state)
    state.data = {**state.data, "crop_asset_id": imaging.store_image(db, result, "diagram"),
        "print_options_embedded": bool(labels), "diagram_crop_fallback": False,
        "image_review_required": True, "print_parts": validated, "print_source_asset_id": source,
        "crop_history": [*state.data.get("crop_history", []), {"source_asset_id": source, "boxes": validated, "day": flow.today()}]}
    db.commit()
    return view(db, qid)


@router.post("/questions/{qid}/image/crop")
def multi_crop(qid: str, body: dict, db: Session = Depends(get_db)):
    return crop(qid, body, db)


@router.post("/questions/{qid}/image/erase")
def erase(qid: str, body: dict, db: Session = Depends(get_db)):
    q = flow.get_question(db, qid)
    state = flow.state_for(db, qid)
    source = checked_source(q, state, body.get("asset_id"))
    if body.get('method') in {'lama','handwriting'}:
        flow.fail('本地模型修复请先生成预览，再采用修复稿','REPAIR_PREVIEW_REQUIRED',422)
    cleaned, _mask = erase_strokes(imaging.load_image(db, source), body.get("strokes"), body.get("method", "white"), body.get('protect_strokes'))
    save_erasure(db,q,state,source,cleaned)
    db.commit()
    return view(db,qid)


def save_erasure(db,q,state,source,cleaned):
    aid = imaging.store_image(db, cleaned)
    remember(state)
    if any(item['asset_id']==source for item in state.data.get('inline_images') or []):
        state.data={**state.data,'inline_images':[{**item,'asset_id':aid,'display_width':round(cleaned.width*20/max(1,item.get('text_height',20)))} if item['asset_id']==source else item for item in state.data['inline_images']], 'image_review_required':True,'image_confirmed_inline_ids':None}
        return
    if source == state.data.get("crop_asset_id") and source != state.data.get("processed_asset_id"):
        state.data = {**state.data, "crop_asset_id": aid, "image_review_required": True}
    else:
        state.data = {**state.data, "processed_asset_id": aid, "image_review_required": True}
        if state.data.get('inline_images'):
            state.data={**state.data,'inline_images':[{**item,'asset_id':imaging.store_image(db,cleaned.crop(imaging.bounds(item['box'],*cleaned.size)),'inline_original')} for item in state.data['inline_images']], 'image_confirmed_inline_ids':None}
        # Re-crop from the edited copy when recorded manual crop geometry exists.
        if state.data.get("print_parts") and state.data.get("print_source_asset_id") == source:
            parts = [(item["label"], cleaned.crop(imaging.bounds(item["box"], *cleaned.size))) for item in state.data["print_parts"]]
            state.data = {**state.data, "crop_asset_id": imaging.store_image(db, diagram_sheet(parts)), "print_source_asset_id": aid}
        elif state.data.get("crop_asset_id") == source:
            state.data = {**state.data, "crop_asset_id": aid}
        else:
            # Do not silently keep an unrelated old crop as the cleaned print.
            state.data = {**state.data, "crop_asset_id": None, "print_options_embedded": False}


@router.get('/image/repair-status')
def repair_status():
    from app.modules.learning.diagram_repair import status
    from app.modules.learning.ink_segmentation import status as ink_status
    from app.modules.learning.document_unwarp import configuration as unwarp_configuration
    from app.modules.learning.local_document_ocr import status as document_status
    return {**status(), 'handwriting_ready':ink_status()['ready'], 'unwarp_ready':unwarp_configuration() is not None,'document_ocr':document_status()}


@router.post('/questions/{qid}/image/enhance-preview')
def enhance_preview(qid: str, body: dict, db: Session = Depends(get_db)):
    import time
    from io import BytesIO
    from app.modules.learning.document_cv import normalize_illumination,printed_angle,rotate_preserving_edges
    q=flow.get_question(db,qid);state=flow.state_for(db,qid)
    source=checked_source(q,state,body.get('asset_id'))
    mode=body.get('mode','paper')
    if mode not in ('paper','deskew','unwarp','ink_layer'):flow.fail('请选择有效的增强或矫正方式','INVALID_IMAGE_MODE',422)
    version=q.current_version_id;snapshot=json.loads(json.dumps({key:state.data.get(key) for key in IMAGE_FIELDS}))
    original=imaging.load_image(db,source);started=time.perf_counter();metrics={'mode':mode}
    if mode=='ink_layer':
        if source in (q.source_asset_id,state.data.get('processed_asset_id')) or original.width*original.height>1_500_000:
            flow.fail('请先选择单个原位图块或打印裁图，再生成笔迹分层预览','INK_REGION_TOO_LARGE',422)
        import numpy as np
        import cv2
        from PIL import Image
        from app.modules.learning.ink_segmentation import page_probabilities
        from app.modules.learning.diagram_processing import stroke_mask
        probability=page_probabilities(original)
        if probability is None:flow.fail('本地笔迹模型尚未就绪','INK_MODEL_NOT_READY',409)
        normalized,ink,_=normalize_illumination(original)
        selected=((probability>=.985)&(np.asarray(ink)>35)).astype('uint8')
        count,labels,stats,_=cv2.connectedComponentsWithStats(selected,8)
        keep=np.zeros(count,dtype='uint8')
        # Tiny isolated components can be decimal/radical dots, not noise.
        for component in range(1,count):
            if stats[component,cv2.CC_STAT_AREA]>=5:keep[component]=255
        mask=keep[labels]
        if body.get('protect_strokes'):
            protect=stroke_mask(original,body['protect_strokes']);mask[np.asarray(protect)>0]=0
        if not mask.any():flow.fail('没有达到高阈值的笔迹像素，请使用局部笔刷标记','NO_CONFIDENT_HANDWRITING',422)
        corrected=Image.fromarray(cv2.inpaint(np.asarray(normalized),mask,2,cv2.INPAINT_TELEA))
        metrics.update({'threshold':.985,'selected_pixels':int((mask>0).sum()),'preview_only':True})
    elif mode=='unwarp':
        if original.width*original.height>4_000_000:flow.fail('请切换到单个公式或题图再矫正','IMAGE_TOO_LARGE',422)
        from app.modules.learning.document_unwarp import unwarp
        corrected,metrics=unwarp(original)
    elif mode=='deskew':
        from app.modules.learning.local_ocr import read
        raw=BytesIO();original.save(raw,'PNG');lines,*_=read(raw.getvalue(),'off',False,'off',False)
        angle=printed_angle(lines,original.size);metrics['angle']=round(angle,3)
        corrected=rotate_preserving_edges(original,angle)
    else:corrected=original
    corrected,_,_=normalize_illumination(corrected)
    db.refresh(q);db.refresh(state)
    if q.current_version_id!=version or snapshot!={key:state.data.get(key) for key in IMAGE_FIELDS}:
        flow.fail('增强期间题目或图像已修改，请从当前副本重新生成','STALE_IMAGE_REPAIR',409)
    # A nonlinear page warp invalidates old source-space crop coordinates.
    # Only single print/inline assets may adopt geometry-changing previews.
    adoptable=mode in ('paper','ink_layer') or (source!=q.source_asset_id and source!=state.data.get('processed_asset_id'))
    state.data={**state.data,'image_repair_draft':{'asset_id':imaging.store_image(db,corrected),'source_asset_id':source,'method':'enhance:'+mode,'seconds':round(time.perf_counter()-started,2),'version_id':version,'image_state':snapshot,'enhancement':metrics,'adoptable':adoptable}}
    db.commit();return view(db,qid)


@router.post('/questions/{qid}/image/repair-preview')
def repair_preview(qid: str, body: dict, db: Session = Depends(get_db)):
    import time
    q=flow.get_question(db,qid)
    state=flow.state_for(db,qid)
    source=checked_source(q,state,body.get('asset_id'))
    starting_version=q.current_version_id
    starting_images=json.loads(json.dumps({key:state.data.get(key) for key in IMAGE_FIELDS}))
    started=time.perf_counter()
    cleaned,mask=erase_strokes(imaging.load_image(db,source),body.get('strokes'),body.get('method','inpaint'),body.get('protect_strokes'))
    db.refresh(q); db.refresh(state)
    checked_source(q,state,source)
    if q.current_version_id != starting_version:
        flow.fail('修复期间题目已修改，请重新生成预览','STALE_IMAGE_REPAIR',409)
    if starting_images != {key:state.data.get(key) for key in IMAGE_FIELDS}:
        flow.fail('修复期间图像已修改，请从当前图像重新生成预览','STALE_IMAGE_REPAIR',409)
    draft={'asset_id':imaging.store_image(db,cleaned),'source_asset_id':source,
        'mask_asset_id':imaging.store_image(db,mask.convert('RGB')),'method':body.get('method','inpaint'),
        'version_id':starting_version,'seconds':round(time.perf_counter()-started,2),'image_state':starting_images}
    state.data={**state.data,'image_repair_draft':draft}
    db.commit()
    return view(db,qid)


@router.post('/questions/{qid}/image/repair-adopt')
def repair_adopt(qid: str, body: dict, db: Session = Depends(get_db)):
    q=flow.get_question(db,qid)
    state=flow.state_for(db,qid)
    draft=state.data.get('image_repair_draft')
    if not draft or draft['asset_id'] != body.get('asset_id'):
        flow.fail('请选择当前题目最新的修复预览','INVALID_IMAGE_SOURCE',422)
    if draft.get('adoptable') is False:
        flow.fail('整页几何矫正会改变框选坐标；请切换到单个原位公式或打印图后再矫正','IMAGE_GEOMETRY_REVIEW',422)
    if draft['version_id'] != q.current_version_id:
        flow.fail('题目已修改，请重新生成预览','STALE_IMAGE_REPAIR',409)
    if draft.get('image_state') is not None and draft['image_state'] != {key:state.data.get(key) for key in IMAGE_FIELDS}:
        flow.fail('图像已修改，请重新生成预览，避免覆盖新裁图','STALE_IMAGE_REPAIR',409)
    source=checked_source(q,state,draft['source_asset_id'])
    save_erasure(db,q,state,source,imaging.load_image(db,draft['asset_id']))
    state.data={**state.data,'image_repair_draft':None}
    db.commit()
    return view(db,qid)


@router.post("/questions/{qid}/image/undo")
def undo(qid: str, db: Session = Depends(get_db)):
    q=flow.get_question(db, qid)
    state = flow.state_for(db, qid)
    history = state.data.get("image_history", [])
    if not history:
        flow.fail("暂无可回退的图像修改", "NO_IMAGE_HISTORY", 409)
    content=flow.question_content(db,q)
    if re.search(r'\[\[图块:\d+\]\]',content.get('stem','')+'\n'+'\n'.join(content.get('options',[]))) and not history[-1].get('inline_images'):
        flow.fail('这次图像修改属于原位排版之前的题目版本，请通过历史版本查看，避免公式图块与题干错配','IMAGE_VERSION_MISMATCH',409)
    state.data = {**{k: v for k, v in state.data.items() if k not in IMAGE_FIELDS}, **history[-1], "image_history": history[:-1]}
    db.commit()
    return view(db, qid)


@router.post("/questions/{qid}/image/confirm")
def confirm(qid: str, db: Session = Depends(get_db)):
    flow.get_question(db, qid)
    state = flow.state_for(db, qid)
    images=state.data.get('inline_images') or []
    if not images or state.data.get('crop_asset_id'):
        imaging.load_image(db, state.data.get("crop_asset_id"))
    for item in images:imaging.load_image(db,item['asset_id'])
    state.data = {**state.data, "image_review_required": False, "image_confirmed_asset_id": state.data.get("crop_asset_id"), 'image_confirmed_inline_ids':[item['asset_id'] for item in images]}
    db.commit()
    return view(db, qid)
