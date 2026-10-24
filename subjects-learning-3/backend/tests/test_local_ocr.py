import importlib.util
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fitz
import pytest
from app.modules.learning import ai, local_ocr
from app.modules.learning.local_ocr import Line
from PIL import Image, ImageDraw


def line(text, x, y, right=None):
    return Line(text, [x, y, right or x + 0.3, y + 0.03])


def test_local_default_needs_no_api_key_and_never_falls_back(client, db, monkeypatch):
    monkeypatch.setattr(
        local_ocr,
        "status",
        lambda: {"ready": True, "formula_ready": False, "message": "本地就绪"},
    )
    data = client.get("/api/v1/learning/settings").json()
    assert data["recognition"]["mode"] == "local"
    assert data["recognition"]["available"]
    assert not data["ai"]["configured"]
    client.patch(
        "/api/v1/learning/settings", json={"ai": {"key": "fake-local-test-key"}}
    )
    external = AsyncMock(side_effect=AssertionError("unexpected paid API"))
    monkeypatch.setattr(ai, "generate", external)
    monkeypatch.setattr(
        local_ocr,
        "recognize",
        lambda *args: (_ for _ in ()).throw(RuntimeError("local failure")),
    )
    monkeypatch.setattr(ai, "image_for", lambda *args: b"photo")
    import asyncio

    with pytest.raises(RuntimeError, match="local failure"):
        asyncio.run(ai.recognize(db, "photo", ""))
    external.assert_not_called()


def test_local_manual_answer_keeps_handwriting(monkeypatch):
    seen = []

    def read(raw, ink, formula):
        seen.append(ink)
        return [line("x = 2", 0.1, 0.1)], [], [], {"engine": "local"}

    monkeypatch.setattr(local_ocr, "read", read)
    result = local_ocr.supplied_answer(b"photo", False)
    assert seen == ["off"]
    assert result["answer"] == "x = 2"
    assert result["explanation"] == ""


def test_graph_labels_are_attached_to_corresponding_figures():
    lines = [
        line("选择正确的图像", 0.1, 0.1),
        line("[B]", 0.65, 0.65, 0.7),
        line("[A]", 0.2, 0.65, 0.25),
    ]
    figures = [
        {"label": "figure", "box": [0.1, 0.3, 0.4, 0.64]},
        {"label": "figure", "box": [0.55, 0.3, 0.85, 0.64]},
    ]
    result = local_ocr.question_from_lines(lines, figures)
    assert result["options"] == ["[A]", "[B]"]
    assert result["stem"] == "选择正确的图像"
    assert result["diagram_regions"][0]["box"][3] >= 0.68
    assert result["diagram_regions"][1]["box"][3] >= 0.68
    assert figures[0]["box"][3] == 0.64  # callers' layout results stay unchanged


def test_two_column_answers_preserve_number_and_geometry():
    lines = [
        line("1. A", 0.06, 0.1),
        line("解析：左边第一题", 0.06, 0.2),
        line("(1) 小问", 0.06, 0.3),
        line("2. C", 0.06, 0.6),
        line("3. B", 0.55, 0.1),
        line("解析：右边第三题", 0.55, 0.2),
        line("4. D", 0.55, 0.6),
    ]
    result = local_ocr.index_from_lines(lines, "第二章", [])
    assert [entry["number"] for entry in result["items"]] == ["1", "2", "3", "4"]
    left, right = result["items"][0], result["items"][2]
    assert left["answer"] == "A"
    assert "小问" in left["explanation"]
    assert right["answer"] == "B"
    assert left["regions"][0]["box"][2] == right["regions"][0]["box"][0]
    assert left["regions"][0]["box"][3] < 0.6


def test_unmarked_continuation_is_never_guessed():
    previous = [{"number": "12", "chapter": "第一章"}]
    result = local_ocr.index_from_lines(
        [line("答案如下", 0.1, 0.1)], "第一章", previous
    )
    assert result["items"] == []
    result = local_ocr.index_from_lines(
        [line("接上页：续解", 0.1, 0.1)], "第一章", previous
    )
    assert result["items"][0]["number"] == "12"


def test_observed_letter_without_brackets_uses_figure_and_label_alignment():
    lines = [
        line("选择图像", 0.1, 0.1),
        line("A", 0.9, 0.4, 0.95),
        line("[A]", 0.2, 0.65, 0.25),
        line("B", 0.65, 0.65, 0.7),
        line("x", 0.8, 0.85, 0.82),
    ]
    figures = [
        {"label": "figure", "box": [0.1, 0.3, 0.4, 0.64]},
        {"label": "figure", "box": [0.55, 0.3, 0.85, 0.64]},
    ]
    result = local_ocr.question_from_lines(lines, figures)
    assert result["options"] == ["[A]", "[B]"]
    assert "A" in result["stem"]  # an unaligned handwritten letter is not an option
    assert not result["stem"].endswith("x")


def test_missing_option_is_reported_without_inventing_it():
    result = local_ocr.question_from_lines(
        [line("原题", 0.1, 0.1), line("[A]", 0.1, 0.5), line("[C]", 0.6, 0.5)], []
    )
    assert result["options"] == ["[A]", "[C]"]
    assert any("缺少B" in note for note in result["concerns"])


def test_unconverted_formula_keeps_original_region_for_printing():
    elements = [{"label": "isolate_formula", "box": [0.1, 0.3, 0.8, 0.5]}]
    result = local_ocr.question_from_lines(
        [line("求x", 0.1, 0.1), line("x2 + 1 = 0", 0.15, 0.35)], elements
    )
    assert result["has_diagram"]
    assert result["stem"] == "求x"
    assert len(result["diagram_regions"]) == 1
    converted = local_ocr.question_from_lines(
        [line("求x", 0.1, 0.1), line("$x^{2}+1=0$", 0.15, 0.35)], elements
    )
    assert not converted["has_diagram"]
    assert "$x^{2}+1=0$" in converted["stem"]


def test_pdf_native_text_avoids_ocr_and_maps_rotated_coordinates(client, monkeypatch):
    monkeypatch.setattr(
        local_ocr,
        "status",
        lambda: {"ready": False, "formula_ready": False, "message": "not installed"},
    )
    monkeypatch.setattr(
        local_ocr,
        "read",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("PDF with text must not OCR")
        ),
    )
    pdf = fitz.open()
    page = pdf.new_page(width=300, height=500)
    page.insert_text((40, 80), "1. A")
    page.set_rotation(90)
    raw = pdf.tobytes()
    pdf.close()
    response = client.post(
        "/api/v1/learning/answer-bank/import",
        data={"book": "native"},
        files={"files": ("native.pdf", raw, "application/pdf")},
    )
    assert response.status_code == 200, response.text
    data = client.get("/api/v1/learning/answer-bank/" + response.json()["id"]).json()
    page = data["pages"][0]
    assert page["status"] == "completed"
    assert page["recognition_info"]["engine"] == "pdf_text"
    assert page["items"][0]["number"] == "1"
    box = page["pdf_text_lines"][0]["box"]
    assert 0.8 < box[0] < 0.9
    assert 0.1 < box[1] < 0.2


def test_color_cleanup_does_not_erase_black_graph():
    if importlib.util.find_spec("cv2") is None:
        pytest.skip("local OCR dependencies are optional")
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.line((10, 10, 90, 10), fill="black", width=3)
    draw.line((20, 30, 80, 30), fill="red", width=3)
    draw.line((20, 50, 80, 50), fill=(190, 170, 164), width=3)
    draw.rectangle((5, 70, 95, 90), fill=(220, 210, 180))
    draw.line((20, 60, 80, 60), fill=(55, 20, 20), width=3)
    clean, removed = local_ocr.clean_color_notes(image, "red")
    assert removed > 0
    assert clean.getpixel((40, 10)) == (0, 0, 0)
    assert clean.getpixel((40, 30))[1] > 200
    assert clean.getpixel((40, 50))[1] > 200
    assert clean.getpixel((40, 80)) == (220, 210, 180)
    assert clean.getpixel((40, 60))[1] > 200
    assert image.getpixel((40, 30)) == (255, 0, 0)


def test_numpy_layout_and_formula_timeout_keep_original_ocr(monkeypatch):
    import numpy as np

    engine = local_ocr.Runtime.__new__(local_ocr.Runtime)
    engine.layout = lambda image: SimpleNamespace(
        boxes=np.array([[0, 0, 100, 100]]),
        class_names=["isolate_formula"],
        scores=np.array([0.9]),
    )
    engine.ocr = lambda image: SimpleNamespace(
        boxes=np.array([[[10, 10], [90, 10], [90, 30], [10, 30]]]),
        txts=["x + 1 = 2"],
        scores=[0.99],
    )
    engine.formula_config = {"encoder_path": "local"}
    engine.formula_python = "local-python"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired("formula", 45)
        ),
    )
    lines, elements, concerns = engine.read(Image.new("RGB", (100, 100), "white"), True)
    assert lines[0].text == "x + 1 = 2"
    assert elements[0]["box"] == [0, 0, 1, 1]
    assert any("公式转录未完成" in note for note in concerns)


def test_text_options_do_not_expand_figure_and_wrapped_choice_stays_with_option():
    result = local_ocr.question_from_lines([
        line("下列说法正确的是（）", .1, .1),
        line("[A] 第一项", .1, .61),
        line("[B] 第二项", .1, .68),
        line("[C] 第三项", .1, .75),
        line("[D] 电场力所", .1, .82),
        line("做的功", .1, .86),
    ], [{"label":"figure", "box":[.08,.3,.8,.58]}])
    assert result['stem'] == '下列说法正确的是（）'
    assert result['options'][-1] == '[D] 电场力所做的功'
    assert result['diagram_regions'][0]['label'] == ''
    assert result['diagram_regions'][0]['box'][3] < .61


def test_question_text_filter_removes_gray_only_and_faded_original_falls_back():
    image = Image.new('RGB', (300,150), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((30,30,100,40), fill=(20,20,20))
    draw.rectangle((30,70,100,75), fill=(170,170,170))
    before = image.tobytes()
    clean, info = local_ocr.question_text_image(image)
    assert info['filtered']
    assert clean.getpixel((60,35)) == (0,0,0)
    assert clean.getpixel((60,73)) == (255,255,255)
    assert image.tobytes() == before
    faded = Image.new('RGB',(300,150),'white')
    ImageDraw.Draw(faded).line((20,30,200,30), fill=(185,185,185),width=3)
    unchanged, info = local_ocr.question_text_image(faded)
    assert not info['filtered'] and unchanged.tobytes() == faded.tobytes()
