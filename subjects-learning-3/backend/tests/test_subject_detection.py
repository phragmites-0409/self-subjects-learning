import pytest

from app.modules.learning import ai
from app.modules.learning.subject_detection import detect_subject


@pytest.mark.parametrize("text,subject", [
    ("已知函数的定义域，求导数及单调区间", "数学"),
    ("静电场的等势线，一带电粒子从A运动到C，比较电势能", "物理"),
    ("简谐横波的周期及波形图", "物理"),
    ("NaOH溶液与盐酸反应后形成沉淀", "化学"),
    ("细胞在减数分裂中染色体与基因的变化", "生物"),
    ("阅读文言文，解释加点字并默写诗句", "语文"),
    ("Read the following passage and choose the best answer to each question.", "英语"),
    ("如图所示，下列说法正确的是", ""),
    ("函数与电场", ""),
    ("x+1=2", "数学"),
    (r"\frac \sqrt \alpha \beta \gamma \delta \omega \theta", ""),
])
def test_local_subject_detection_abstains_on_ambiguous_text(text, subject):
    assert detect_subject(text)["subject"] == subject


def test_text_intake_defaults_to_auto_and_allows_manual_correction(client):
    q = client.post("/api/v1/learning/intake", json={
        "text": "电场中的粒子具有电势能", "is_error": True,
    }).json()
    assert q["subject"] == "物理" and q["data"]["subject_source"] == "auto"
    corrected = client.patch(f"/api/v1/learning/questions/{q['id']}",
                             json={"subject": "数学"}).json()
    assert corrected["subject"] == "数学"
    assert corrected["data"]["subject_source"] == "manual"


def test_unknown_auto_subject_requires_a_selection_before_archive(client):
    q = client.post("/api/v1/learning/intake", json={"text": "如图所示"}).json()
    assert q["data"]["subject_source"] == "unknown"
    result = client.post(f"/api/v1/learning/questions/{q['id']}/archive")
    assert result.status_code == 409 and "学科" in result.text
    # Explicitly selecting the current internal fallback counts as confirmation.
    selected = client.patch(f"/api/v1/learning/questions/{q['id']}",
                            json={"subject": "数学"}).json()
    assert selected["data"]["subject_source"] == "manual"


@pytest.mark.parametrize("selected,expected,source", [("", "物理", "auto"), ("生物", "生物", "manual")])
def test_photo_ocr_applies_subject_only_when_user_has_not_selected_one(
    client, monkeypatch, png_bytes, selected, expected, source,
):
    monkeypatch.setattr(ai, "recognition_available", lambda db: True)

    async def recognize(*args):
        return ai.Recognition(stem="电场中的粒子具有电势能", subject="物理")

    monkeypatch.setattr(ai, "recognize", recognize)
    uploaded = client.post("/api/v1/assets", files={"file": ("q.png", png_bytes, "image/png")}).json()
    qid = uploaded["question_id"]
    result = client.post("/api/v1/learning/intake", json={"question_id": qid, "subject": selected})
    assert result.status_code == 200
    q = client.get(f"/api/v1/learning/questions/{qid}").json()
    assert q["subject"] == expected and q["data"]["subject_source"] == source
    assert q["data"]["recognition"] == "completed"
    # A retry remains a review draft and cannot change confirmed classification or answers.
    client.patch(f"/api/v1/learning/questions/{qid}", json={"subject": "化学"})
    client.post(f"/api/v1/learning/questions/{qid}/answer", json={"answer": "B"})
    assert client.post(f"/api/v1/learning/questions/{qid}/recognize").status_code == 200
    q = client.get(f"/api/v1/learning/questions/{qid}").json()
    assert q["subject"] == "化学" and q["answer"] == "B" and q["answer_confirmed"]
    assert q["data"]["recognition_draft"]["subject"] == "物理"


def test_auto_english_intake_does_not_create_a_four_science_error(client):
    q = client.post("/api/v1/learning/intake", json={
        "text": "Read the following passage and choose the best answer to each question.",
        "is_error": True,
    }).json()
    client.post(f"/api/v1/learning/questions/{q['id']}/answer", json={"answer": "A"})
    result = client.post(f"/api/v1/learning/questions/{q['id']}/archive")
    assert result.status_code == 200 and result.json()["subject"] == "英语"
    assert result.json()["occurrences"] == []
