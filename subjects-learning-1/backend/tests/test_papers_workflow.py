from __future__ import annotations

import base64
import re
import zlib

from app.core.config import get_settings
from app.db.models import Asset, Paper, QuestionVersion
from app.documents.pdf_service import _font, generate_paper_pdf
from app.storage.local_store import LocalFilesystemContentStore


def _decoded_pdf_streams(data: bytes) -> bytes:
    decoded = bytearray()
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.DOTALL):
        stream = match.group(1).strip()
        try:
            if stream.endswith(b"~>"):
                stream = base64.a85decode(stream[:-2])
            stream = zlib.decompress(stream)
        except (ValueError, zlib.error):
            pass
        decoded.extend(stream)
    return bytes(decoded)


def _cid_ascii_pdf_bytes(text: str) -> bytes:
    assert text.isascii()
    return b"".join(b"\\000" + character.encode() for character in text)


def test_pdf_uses_builtin_simplified_chinese_font_by_default():
    assert _font(None) == "STSong-Light"


def test_generate_paper_pdf_creates_readable_pdf_file():
    output = get_settings().data_dir / "tmp" / "standalone-paper.pdf"

    generate_paper_pdf(
        "Algebra paper",
        [{"content": {"stem": "Solve x + 1 = 2", "answer": "x = 1"}, "points": 5}],
        output,
    )

    data = output.read_bytes()
    assert data.startswith(b"%PDF-")
    assert data.rstrip().endswith(b"%%EOF")
    assert len(data) > 1000
    output.unlink()


def test_paper_rejects_version_owned_by_a_different_question(client, question_factory):
    first_question, _ = question_factory(stem="First question")
    _, second_version = question_factory(stem="Second question")

    response = client.post(
        "/api/v1/papers",
        json={
            "title": "Version ownership",
            "items": [
                {
                    "question_id": first_question.id,
                    "question_version_id": second_version.id,
                    "points": 10,
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PAPER_VERSION_INVALID"


def test_paper_pins_selected_version_when_question_changes(client, db, question_factory):
    question, first_version = question_factory(stem="Version one", answer="A1")
    updated = client.patch(
        f"/api/v1/questions/{question.id}",
        json={"content": {"stem": "Version two", "answer": "A2"}},
    )
    assert updated.status_code == 200

    response = client.post(
        "/api/v1/papers",
        json={
            "title": "Pinned version",
            "items": [
                {
                    "question_id": question.id,
                    "question_version_id": first_version.id,
                    "points": 7.5,
                    "section_name": "基础题",
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_points"] == 7.5
    assert body["items"][0]["question_version_id"] == first_version.id
    db.expire_all()
    assert db.get(QuestionVersion, body["items"][0]["question_version_id"]).version_number == 1


def test_student_and_answer_exports_have_distinct_content_and_download(client, db, question_factory):
    question, _ = question_factory(stem="Solve x + 1 = 2", answer="ANSWER_TOKEN_314159")
    created = client.post(
        "/api/v1/papers",
        json={"title": "Algebra paper", "items": [{"question_id": question.id, "points": 5}]},
    )
    assert created.status_code == 200
    paper_id = created.json()["id"]

    student = client.post(f"/api/v1/papers/{paper_id}/export", params={"include_answers": False})
    answer = client.post(f"/api/v1/papers/{paper_id}/export", params={"include_answers": True})

    assert student.status_code == answer.status_code == 200
    student_asset_id = student.json()["asset_id"]
    answer_asset_id = answer.json()["asset_id"]
    assert student_asset_id != answer_asset_id
    student_download = client.get(student.json()["download_url"])
    answer_download = client.get(answer.json()["download_url"])
    assert student_download.status_code == answer_download.status_code == 200
    assert student_download.headers["content-type"].startswith("application/pdf")
    assert answer_download.headers["content-type"].startswith("application/pdf")
    student_streams = _decoded_pdf_streams(student_download.content)
    answer_streams = _decoded_pdf_streams(answer_download.content)
    answer_token = _cid_ascii_pdf_bytes("ANSWER_TOKEN_314159")
    assert answer_token not in student_streams
    assert answer_token in answer_streams
    db.expire_all()
    paper = db.get(Paper, paper_id)
    assert paper.status == "generated"
    assert paper.student_pdf_asset_id == student_asset_id
    assert paper.answer_pdf_asset_id == answer_asset_id
    assert db.get(Asset, student_asset_id).byte_size == len(student_download.content)
    assert db.get(Asset, answer_asset_id).byte_size == len(answer_download.content)
    assert LocalFilesystemContentStore().path_for(db.get(Asset, answer_asset_id).storage_key).exists()
