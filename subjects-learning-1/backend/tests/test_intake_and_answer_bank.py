from io import BytesIO

import fitz
import pytest
from app.ai.contracts import LLMResponse
from app.core.errors import AppError
from app.modules.learning import ai
from app.modules.learning import service as flow
from app.modules.learning.models import Occurrence, RoundItem
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from sqlalchemy import select


def draft(client):
    response = client.post(
        "/api/v1/learning/intake",
        json={"text": "x+1=2", "subject": "数学", "is_error": True},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def assign(client, qid):
    node = client.post(
        "/api/v1/learning/knowledge",
        json={"subject": "数学", "kind": "type", "name": "方程"},
    ).json()
    response = client.patch(
        f"/api/v1/learning/questions/{qid}",
        json={"topic_id": node["id"], "tags": ["重点题"], "minutes": 5},
    )
    assert response.status_code == 200
    return node["id"]


def test_draft_is_hidden_from_both_libraries_and_cannot_be_paper_or_error(client, db):
    qid = draft(client)
    assert client.get("/api/v1/learning/questions").json()["items"] == []
    assert client.get("/api/v1/questions").json()["items"] == []
    assert (
        client.get("/api/v1/learning/questions?filter=draft").json()["items"][0]["id"]
        == qid
    )
    assert (
        client.post(f"/api/v1/learning/questions/{qid}/error", json={}).status_code
        == 409
    )
    assert client.post(f"/api/v1/questions/{qid}/approve").status_code == 409
    response = client.post(
        "/api/v1/papers",
        json={"title": "Test", "subject": "数学", "items": [{"question_id": qid}]},
    )
    assert response.status_code == 422
    assert db.query(Occurrence).count() == 0


def test_archive_requires_type_and_answer_then_adds_error_exactly_once(client, db):
    qid = draft(client)
    assert client.post(f"/api/v1/learning/questions/{qid}/archive").status_code == 409
    assign(client, qid)
    assert client.post(f"/api/v1/learning/questions/{qid}/archive").status_code == 409
    result = client.post(
        f"/api/v1/learning/questions/{qid}/answer", json={"answer": "1"}
    ).json()
    assert result["answer_confirmed"] and result["data"]["answer_source"] == "manual"
    result = client.post(f"/api/v1/learning/questions/{qid}/archive")
    assert result.status_code == 200 and result.json()["status"] == "approved"
    assert len(result.json()["occurrences"]) == 1
    assert client.get("/api/v1/learning/questions").json()["items"][0]["id"] == qid
    assert client.post(f"/api/v1/learning/questions/{qid}/archive").status_code == 200
    db.expire_all()
    assert db.query(Occurrence).count() == 1


def test_manual_explanation_only_is_not_judged_or_forced_into_both_fields(
    client, monkeypatch
):
    qid = draft(client)
    assign(client, qid)

    async def never(*args, **kwargs):
        pytest.fail("Manual input must not ask AI to solve or judge")

    monkeypatch.setattr(ai, "analyze", never)
    result = client.post(
        f"/api/v1/learning/questions/{qid}/answer", json={"explanation": "两边同时减一"}
    ).json()
    assert result["answer"] == "" and result["answer_confirmed"]
    assert client.post(f"/api/v1/learning/questions/{qid}/archive").status_code == 200


def test_ai_answer_requires_both_fields_and_explicit_confirmation(client, monkeypatch):
    qid = draft(client)
    assign(client, qid)

    async def analyze(*args, **kwargs):
        return ai.Analysis(answer_draft="1", explanation="两边减去1，得x=1")

    monkeypatch.setattr(ai, "analyze", analyze)
    assert client.post(f"/api/v1/learning/questions/{qid}/analysis").status_code == 200
    result = client.post(f"/api/v1/learning/questions/{qid}/answer/use-ai").json()
    assert not result["answer_confirmed"] and result["data"]["answer_explanation"]
    assert client.post(f"/api/v1/learning/questions/{qid}/archive").status_code == 409
    assert (
        client.patch(
            f"/api/v1/learning/questions/{qid}", json={"answer_confirmed": True}
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/learning/questions/{qid}/archive").status_code == 200


@pytest.mark.parametrize("answer,explanation", [("", "步骤"), ("1", "")])
def test_ai_generation_rejects_missing_answer_or_explanation(
    client, db, monkeypatch, answer, explanation
):
    async def generate(*args, **kwargs):
        return ai.Analysis(answer_draft=answer, explanation=explanation)

    monkeypatch.setattr(ai, "generate", generate)
    with pytest.raises(AppError, match="未同时给出"):
        import asyncio

        asyncio.run(ai.analyze(db, {"stem": "x+1=2"}, None))


def test_answer_photo_is_confirmed_without_ai_and_original_bytes_preserved(
    client, png_bytes
):
    qid = draft(client)
    assign(client, qid)
    upload = client.post(
        "/api/v1/assets",
        files={"file": ("a.png", png_bytes, "image/png")},
        data={"purpose": "answer"},
    ).json()
    result = client.post(
        f"/api/v1/learning/questions/{qid}/answer",
        json={"asset_id": upload["asset_id"]},
    ).json()
    assert result["answer_confirmed"] and result["data"]["answer_asset_ids"] == [
        upload["asset_id"]
    ]
    assert (
        client.get(f"/api/v1/assets/{upload['asset_id']}/download").content == png_bytes
    )
    assert client.post(f"/api/v1/learning/questions/{qid}/archive").status_code == 200


def import_photo(client, png_bytes, copies=1):
    result = client.post(
        "/api/v1/learning/answer-bank/import",
        data={"book": "练习册", "chapter": "第一章"},
        files=[
            ("files", (f"answer-{idx}.png", png_bytes, "image/png"))
            for idx in range(copies)
        ],
    )
    assert result.status_code == 200, result.text
    return result.json()


def entries(number="2", box=None, answer="2"):
    return {
        "number": number,
        "chapter": "第一章",
        "answer": answer,
        "explanation": "原解析",
        "regions": [{"box": box or [0.5, 0, 1, 1]}],
    }


def test_whole_page_bank_crops_exact_selected_question_and_keeps_full_page(
    client, png_bytes
):
    doc = import_photo(client, png_bytes)
    page = doc["pages"][0]
    result = client.patch(
        f"/api/v1/learning/answer-bank/pages/{page['id']}",
        json={"items": [entries("1", [0, 0, 0.5, 1], "1"), entries()]},
    )
    assert result.status_code == 200
    matches = client.get(
        "/api/v1/learning/answer-bank/lookup",
        params={"book": "练习册", "chapter": "第一章", "number": "2"},
    ).json()["items"]
    assert len(matches) == 1 and len(matches[0]["entries"]) == 1
    qid = draft(client)
    assign(client, qid)
    result = client.post(
        f"/api/v1/learning/answer-bank/apply/{qid}",
        json={"document_id": doc["id"], "chapter": "第一章", "number": "2"},
    ).json()
    assert result["answer"] == "2" and result["answer_confirmed"]
    crop = Image.open(
        BytesIO(
            client.get(
                f"/api/v1/assets/{result['data']['answer_asset_ids'][0]}/download"
            ).content
        )
    )
    original = Image.open(BytesIO(png_bytes))
    assert crop.size == (40, 40) and crop.getpixel((0, 0)) == original.getpixel((40, 0))
    assert (
        client.get(f"/api/v1/assets/{doc['source_asset_id']}/download").content
        == png_bytes
    )
    assert client.post(f"/api/v1/learning/questions/{qid}/archive").status_code == 200


def test_cross_page_answer_returns_all_parts_and_is_frozen_in_round(
    client, db, png_bytes
):
    doc = import_photo(client, png_bytes, copies=2)
    for page in doc["pages"]:
        assert (
            client.patch(
                f"/api/v1/learning/answer-bank/pages/{page['id']}",
                json={"items": [entries()]},
            ).status_code
            == 200
        )
    qid = draft(client)
    assign(client, qid)
    result = client.post(
        f"/api/v1/learning/answer-bank/apply/{qid}",
        json={"document_id": doc["id"], "chapter": "第一章", "number": "2"},
    ).json()
    assert len(result["data"]["answer_asset_ids"]) == 2
    client.post(f"/api/v1/learning/questions/{qid}/archive")
    state = flow.state_for(db, qid)
    r = flow.make_round(db, "error", "数学", flow.today(), flow.today(), [state])
    db.commit()
    frozen = db.scalar(select(RoundItem).where(RoundItem.round_id == r.id))
    saved = frozen.data["answer_asset_ids"]
    client.post(
        f"/api/v1/learning/questions/{qid}/answer", json={"answer": "修改后的答案"}
    )
    db.refresh(frozen)
    assert frozen.data["answer_asset_ids"] == saved and frozen.data["answer"] == "2"


def test_pdf_import_preserves_pdf_and_renders_all_pages(client):
    with fitz.open() as pdf:
        for text in ("1. Answer: A", "2. Answer: B"):
            page = pdf.new_page(width=400, height=500)
            page.insert_text((40, 80), text)
        raw = pdf.tobytes()
    result = client.post(
        "/api/v1/learning/answer-bank/import",
        data={"book": "PDF答案"},
        files={"files": ("answers.pdf", raw, "application/pdf")},
    )
    assert result.status_code == 200, result.text
    doc = result.json()
    assert doc["page_count"] == 2 and doc["pages"][0]["status"] == "manual"
    indexed = client.get(f"/api/v1/learning/answer-bank/{doc['id']}").json()
    # Restored API version keeps unconfigured OCR pages manual; it must not
    # invoke local OCR or fabricate an index when no API key is configured.
    assert all(page["status"] == "manual" and not page["items"] for page in indexed["pages"])
    assert (
        client.get(f"/api/v1/assets/{doc['source_asset_id']}/download").content == raw
    )
    image = Image.open(
        BytesIO(
            client.get(f"/api/v1/assets/{doc['pages'][0]['asset_id']}/download").content
        )
    )
    assert image.size == (1000, 1250)


def test_bank_auto_indexes_existing_answers_without_solving(
    client, monkeypatch, png_bytes
):
    client.patch(
        "/api/v1/learning/settings",
        json={"ai": {"key": "fake"}, "recognition": {"mode": "api"}},
    )
    called = []

    async def index(db, aid, chapter, previous):
        called.append((chapter, previous))
        return ai.AnswerIndex(items=[ai.IndexedAnswer.model_validate(entries())])

    monkeypatch.setattr(ai, "index_answers", index)
    doc = import_photo(client, png_bytes, copies=2)
    result = client.get(f"/api/v1/learning/answer-bank/{doc['id']}").json()
    assert result["indexed_count"] == 2 and not result["pending"]
    assert len(called) == 2 and called[1][1][0]["number"] == "2"


def test_failed_bank_index_keeps_original_and_is_retryable(
    client, monkeypatch, png_bytes
):
    client.patch(
        "/api/v1/learning/settings",
        json={"ai": {"key": "fake"}, "recognition": {"mode": "api"}},
    )

    async def fail(*args):
        raise RuntimeError("vision unavailable")

    monkeypatch.setattr(ai, "index_answers", fail)
    doc = import_photo(client, png_bytes)
    result = client.get(f"/api/v1/learning/answer-bank/{doc['id']}").json()
    assert result["pages"][0]["status"] == "failed"
    assert (
        client.get(f"/api/v1/assets/{doc['source_asset_id']}/download").content
        == png_bytes
    )


def test_invalid_coordinates_rejected_without_corrupting_index(client, png_bytes):
    doc = import_photo(client, png_bytes)
    page = doc["pages"][0]
    result = client.patch(
        f"/api/v1/learning/answer-bank/pages/{page['id']}",
        json={"items": [entries(box=[0.9, 0, 0.1, 1])]},
    )
    assert result.status_code == 422
    assert (
        client.get(f"/api/v1/learning/answer-bank/{doc['id']}").json()["indexed_count"]
        == 0
    )


def test_automatic_diagrams_and_note_cleanup_never_change_original(
    client, monkeypatch, png_bytes
):
    client.patch(
        "/api/v1/learning/settings",
        json={"ai": {"key": "fake"}, "recognition": {"mode": "api"}},
    )

    async def recognize(*args):
        return ai.Recognition(
            stem="题干",
            has_diagram=True,
            diagram_regions=[ai.ImageRegion(box=[0.5, 0, 1, 1])],
            handwriting_regions=[ai.ImageRegion(box=[0, 0, 0.2, 0.5])],
        )

    monkeypatch.setattr(ai, "recognize", recognize)
    uploaded = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    client.post(
        "/api/v1/learning/intake", json={"question_id": uploaded["question_id"]}
    )
    result = client.get(f"/api/v1/learning/questions/{uploaded['question_id']}").json()
    assert result["status"] == "draft" and result["data"]["recognition"] == "completed"
    crop = Image.open(
        BytesIO(
            client.get(
                f"/api/v1/assets/{result['data']['crop_asset_id']}/download"
            ).content
        )
    )
    assert crop.size == (40, 40)
    cleaned = Image.open(
        BytesIO(
            client.get(
                f"/api/v1/assets/{result['data']['processed_asset_id']}/download"
            ).content
        )
    )
    assert cleaned.getpixel((2, 2)) == (255, 255, 255)
    assert (
        client.get(f"/api/v1/assets/{uploaded['asset_id']}/download").content
        == png_bytes
    )


def test_note_cleanup_protects_diagrams_even_if_ai_marks_overlap_as_handwriting(
    client, monkeypatch, png_bytes
):
    client.patch(
        "/api/v1/learning/settings",
        json={"ai": {"key": "fake"}, "recognition": {"mode": "api"}},
    )
    isolated = [0, 0, 0.2, 0.5]
    overlapping = [0.55, 0.2, 0.75, 0.7]

    async def recognize(*args):
        return ai.Recognition(
            stem="题干",
            has_diagram=True,
            diagram_regions=[ai.ImageRegion(box=[0.5, 0, 1, 1])],
            handwriting_regions=[
                ai.ImageRegion(box=isolated),
                ai.ImageRegion(box=overlapping),
            ],
        )

    monkeypatch.setattr(ai, "recognize", recognize)
    uploaded = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    client.post(
        "/api/v1/learning/intake", json={"question_id": uploaded["question_id"]}
    )
    result = client.get(f"/api/v1/learning/questions/{uploaded['question_id']}").json()
    assert result["data"]["removed_note_regions"] == [isolated]
    assert result["data"]["protected_note_regions"] == [overlapping]
    assert "已保留" in result["data"]["recognition_note"]
    cleaned = Image.open(
        BytesIO(
            client.get(
                f"/api/v1/assets/{result['data']['processed_asset_id']}/download"
            ).content
        )
    )
    expected = Image.open(BytesIO(png_bytes)).convert("RGB")
    ImageDraw.Draw(expected).rectangle((0, 0, 15, 19), fill="white")
    expected = ImageOps.autocontrast(expected, cutoff=0.3, preserve_tone=True)
    expected = expected.filter(
        ImageFilter.UnsharpMask(radius=1, percent=110, threshold=3)
    )
    assert cleaned.tobytes() == expected.tobytes()
    assert (
        client.get(f"/api/v1/assets/{uploaded['asset_id']}/download").content
        == png_bytes
    )


def test_graphical_choices_keep_whole_question_to_preserve_option_matching(
    client, monkeypatch, png_bytes
):
    client.patch(
        "/api/v1/learning/settings",
        json={"ai": {"key": "fake"}, "recognition": {"mode": "api"}},
    )

    async def recognize(*args):
        return ai.Recognition(
            stem="选出正确图像",
            has_diagram=True,
            options=["[A]", "[B]"],
            diagram_regions=[ai.ImageRegion(box=[0.5, 0, 1, 1])],
        )

    monkeypatch.setattr(ai, "recognize", recognize)
    uploaded = client.post(
        "/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}
    ).json()
    client.post(
        "/api/v1/learning/intake", json={"question_id": uploaded["question_id"]}
    )
    result = client.get(f"/api/v1/learning/questions/{uploaded['question_id']}").json()
    assert result["data"]["diagram_crop_fallback"] is True
    assert "选项编号与图形匹配" in result["data"]["recognition_note"]
    assert result["data"]["crop_asset_id"] == result["data"]["processed_asset_id"]
    crop = Image.open(
        BytesIO(
            client.get(
                f"/api/v1/assets/{result['data']['crop_asset_id']}/download"
            ).content
        )
    )
    assert crop.size == Image.open(BytesIO(png_bytes)).size


def test_ai_grading_receives_frozen_reference_photos(
    client, db, monkeypatch, png_bytes
):
    upload = client.post(
        "/api/v1/assets",
        files={"file": ("a.png", png_bytes, "image/png")},
        data={"purpose": "answer"},
    ).json()
    client.patch(
        "/api/v1/learning/settings",
        json={"ai": {"key": "fake"}, "recognition": {"mode": "api"}},
    )
    captured = []

    async def generate(self, request):
        captured.append(request)
        return LLMResponse(text='{"items":[],"concerns":[]}', model="test")

    monkeypatch.setattr(ai.DeepSeekProvider, "generate", generate)
    import asyncio

    asyncio.run(
        ai.grade(
            db,
            [
                {
                    "number": 1,
                    "answer": "",
                    "answer_confirmed": True,
                    "answer_asset_ids": [upload["asset_id"]],
                }
            ],
            upload["asset_id"],
        )
    )
    assert len(captured[0].additional_image_bytes) == 1
    assert '"reference_image_positions": [2]' in captured[0].user_text
