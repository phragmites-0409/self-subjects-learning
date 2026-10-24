from io import BytesIO

import pytest
from PIL import Image

from app.db.models import Question
from app.modules.learning import ai, imaging
from app.modules.learning.question_pages import merge_pages, preserve_observed_labels


def photo(color, size=(100, 80)):
    buffer = BytesIO(); Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def upload(client):
    raw = [photo("red"), photo("blue", (60, 100))]
    result = client.post("/api/v1/learning/intake/photos", files=[("files", (f"page-{i}.png", data, "image/png")) for i, data in enumerate(raw)])
    assert result.status_code == 200, result.text
    return result.json(), raw


def test_ordered_sources_preserve_original_bytes_and_create_only_one_question(client, db):
    uploaded, raw = upload(client)
    assert db.query(Question).count() == 1
    q = client.get(f"/api/v1/learning/questions/{uploaded['question_id']}").json()
    pages = q["data"]["source_pages"]
    for page, original in zip(pages, raw):
        assert client.get(f"/api/v1/assets/{page['asset_id']}/download").content == original
    image = imaging.load_image(db, q["source_asset_id"])
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((0, image.height - 1)) == (0, 0, 255)
    assert pages[0]["box"][3] < pages[1]["box"][1]


@pytest.mark.parametrize("count", [1, 9])
def test_invalid_page_count_does_not_create_questions(client, db, count):
    result = client.post("/api/v1/learning/intake/photos", files=[("files", ("page.png", photo("white"), "image/png")) for _ in range(count)])
    assert result.status_code == 422 and db.query(Question).count() == 0


def test_invalid_later_photo_does_not_create_a_partial_question(client, db):
    result = client.post("/api/v1/learning/intake/photos", files=[("files", ("page.png", photo("white"), "image/png")), ("files", ("bad.png", b"bad", "image/png"))])
    assert result.status_code == 422 and db.query(Question).count() == 0


def test_option_continuation_and_graphic_coordinates_merge_across_pages():
    outputs = [
        {"stem": "电场中的带电粒子", "options": ["[A] 第一项", "[B] 前半句"], "diagram_regions": [{"label": "", "box": [.2, .2, .8, .8]}]},
        {"stem": "后半句", "options": ["[C] 第三项", "[D] 第四项"], "metadata": {"leading_text": "后半句"}, "diagram_regions": [{"label": "", "box": [.2, .2, .8, .8]}]},
    ]
    pages = [{"box": [0, 0, 1, .4]}, {"box": [0, .5, 1, 1]}]
    merged = merge_pages(outputs, pages)
    assert merged["stem"] == "电场中的带电粒子"
    assert merged["options"][1] == "[B] 前半句\n后半句"
    assert merged["diagram_regions"][0]["box"] == pytest.approx([.2, .08, .8, .32])
    assert merged["diagram_regions"][1]["box"] == pytest.approx([.2, .6, .8, .9])
    assert merged["subject"] == "物理"


def test_overlap_removes_only_exact_text_and_conflicting_choices_are_retained():
    outputs = [{"stem": "题干\n同一句", "options": ["[A] 甲"]}, {"stem": "同一句\n续文", "options": ["[A] 乙"]}]
    merged = merge_pages(outputs, [{"box": [0, 0, 1, .5]}, {"box": [0, .5, 1, 1]}])
    assert merged["stem"] == "题干\n同一句\n续文"
    assert merged["options"] == ["[A] 甲", "[A] 乙"]
    assert any("同编号" in note for note in merged["concerns"])


def test_each_photo_is_recognized_independently_and_retry_keeps_manual_answer(client, monkeypatch):
    uploaded, _raw = upload(client)
    pages = uploaded["source_pages"]
    calls = []
    monkeypatch.setattr(ai, "recognition_available", lambda db: True)

    async def recognize(db, aid, hint):
        calls.append(aid)
        return ai.Recognition(stem="电场中的带电粒子" if aid == pages[0]["asset_id"] else "续页条件", options=["[A] 甲", "[B] 乙"] if aid == pages[0]["asset_id"] else ["[C] 丙", "[D] 丁"], subject="物理")

    monkeypatch.setattr(ai, "recognize", recognize)
    qid = uploaded["question_id"]
    client.post("/api/v1/learning/intake", json={"question_id": qid})
    q = client.get(f"/api/v1/learning/questions/{qid}").json()
    assert calls == [page["asset_id"] for page in pages]
    assert q["data"]["recognition"] == "completed" and q["subject"] == "物理"
    assert q["content"]["options"] == ["[A] 甲", "[B] 乙", "[C] 丙", "[D] 丁"]
    client.post(f"/api/v1/learning/questions/{qid}/answer", json={"answer": "B"})
    version = q["version_id"]
    client.post(f"/api/v1/learning/questions/{qid}/recognize")
    q = client.get(f"/api/v1/learning/questions/{qid}").json()
    assert q["version_id"] == version and q["answer"] == "B" and q["answer_confirmed"]
    assert len(q["data"]["recognition_draft"]["options"]) == 4


def test_optional_analysis_receives_all_original_photos_in_order(client, monkeypatch):
    uploaded, _raw = upload(client)
    qid = uploaded["question_id"]
    seen = []

    async def analyze(db, content, aid, extra_aids=None):
        seen.extend([aid, *extra_aids])
        return ai.Analysis(answer_draft="B", explanation="解析")

    monkeypatch.setattr(ai, "analyze", analyze)
    assert client.post(f"/api/v1/learning/questions/{qid}/analysis").status_code == 200
    assert seen == [page["asset_id"] for page in uploaded["source_pages"]]


def test_processed_retry_can_preserve_only_previously_observed_graphical_labels():
    content = {"options": ["[A]", "[B]", "[C]", "[D]"]}
    regions = [{"label": label, "box": [0, .1, 1, .2]} for label in "ABCD"]
    merged = {"options": ["[A]", "[C]", "[D]"], "diagram_regions": [], "has_diagram": True, "concerns": []}
    result = preserve_observed_labels(merged, content, regions)
    assert result["options"] == content["options"] and result["diagram_regions"] == regions
    assert "漏读B" in result["concerns"][0]
    # A conflicting new label or incomplete old geometry cannot supply missing choices.
    assert preserve_observed_labels({**merged, "options": ["[A]", "[E]"]}, content, regions)["options"] == ["[A]", "[E]"]
    assert preserve_observed_labels(merged, content, regions[:2])["options"] == merged["options"]
