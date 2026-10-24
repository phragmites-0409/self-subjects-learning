from __future__ import annotations

import pytest
from app.ai.contracts import LLMRequest
from app.ai.providers.deepseek import DeepSeekProvider
from app.ai.schemas import PreflightResult, QuestionContentV1
from app.ai.validator import extract_json, validate_output
from app.core.config import PROJECT_ROOT, Settings, get_settings
from app.core.errors import AppError


def test_health_reports_backend_ready_without_ai_key(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "application_id": "subjects-learning",
        "version": "-3",
        "data_directory": str(get_settings().data_dir),
        "app": "高中题目 AI 学习本地端",
        "ai_configured": False,
    }


def test_default_data_directory_does_not_follow_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert Settings(_env_file=None).data_dir == PROJECT_ROOT / "data"


@pytest.mark.parametrize("relative", ["data", "custom-data"])
def test_relative_data_directory_is_anchored_to_project(monkeypatch, tmp_path, relative):
    monkeypatch.chdir(tmp_path)
    settings = Settings(data_dir=relative, _env_file=None)
    assert settings.data_dir == PROJECT_ROOT / relative


def test_absolute_data_directory_remains_isolated(tmp_path):
    assert Settings(data_dir=tmp_path, _env_file=None).data_dir == tmp_path.resolve()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"decision":"ready"}', {"decision": "ready"}),
        ('```json\n{"decision":"needs_more_info"}\n```', {"decision": "needs_more_info"}),
        ('模型说明：\n{"decision":"uncertain","concerns":["模糊"]}\n请复核。', {"decision": "uncertain", "concerns": ["模糊"]}),
    ],
)
def test_extract_json_accepts_supported_ai_wrappers(text, expected):
    assert extract_json(text) == expected


@pytest.mark.parametrize("text", ["not json", "[1, 2, 3]", '{"decision":'])
def test_extract_json_rejects_non_object_or_malformed_ai_output(text):
    with pytest.raises(AppError) as caught:
        extract_json(text)

    assert caught.value.code == "AI_INVALID_JSON"
    assert caught.value.status_code == 502


def test_validate_output_rejects_wrong_schema_literal():
    with pytest.raises(AppError) as caught:
        validate_output(
            '{"schema_version":"wrong-version","decision":"ready","is_high_school":true}',
            PreflightResult,
        )

    assert caught.value.code == "AI_SCHEMA_INVALID"
    assert caught.value.status_code == 502
    assert caught.value.details["errors"][0]["loc"] == ("schema_version",)


def test_validate_output_rejects_out_of_range_confidence():
    with pytest.raises(AppError) as caught:
        validate_output(
            '{"schema_version":"question-content-v1","confidence":1.01}',
            QuestionContentV1,
        )

    assert caught.value.code == "AI_SCHEMA_INVALID"
    assert caught.value.details["errors"][0]["loc"] == ("confidence",)


def test_deepseek_provider_routes_image_requests_to_vision_model():
    settings = Settings(
        deepseek_api_key="test-key",
        deepseek_model="deepseek-chat",
        deepseek_vision_model="deepseek-v4-flash-vision-exp",
    )
    provider = DeepSeekProvider(settings)

    assert provider.model_for(LLMRequest("preflight", "policy", "题目", b"image")) == "deepseek-v4-flash-vision-exp"
    assert provider.model_for(LLMRequest("review", "policy", "解析")) == "deepseek-chat"
