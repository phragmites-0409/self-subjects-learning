import asyncio
import json

import httpx
import pytest
from app.ai.contracts import LLMRequest, LLMResponse
from app.ai.providers.deepseek import DeepSeekProvider
from app.ai.validator import structured_prompt, validate_output
from app.core.config import Settings
from app.core.errors import AppError
from app.modules.learning import ai


def completion(content, finish="stop", **message):
    return {"choices": [{"message": {"content": content, **message}, "finish_reason": finish}], "usage": {"completion_tokens": 6000}}


def run_provider(monkeypatch, responses, request=None):
    calls = []

    async def post(self, url, **kwargs):
        calls.append(json.loads(json.dumps(kwargs["json"])))
        status, body = responses[len(calls) - 1]
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    provider = DeepSeekProvider(Settings(deepseek_api_key="test-key"))
    return calls, lambda: asyncio.run(provider.generate(request or LLMRequest("recognize_only", "JSON", "原题")))


def test_ocr_disables_default_thinking_and_preserves_image_and_json_mode(monkeypatch):
    request = LLMRequest("recognize_only", "JSON", "原题", b"image", "image/png")
    calls, run = run_provider(monkeypatch, [(200, completion('{"stem":"原题"}'))], request)
    assert run().text == '{"stem":"原题"}'
    assert calls[0]["thinking"] == {"type": "disabled"}
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("content,finish,code", [
    ("", "length", "AI_OUTPUT_TRUNCATED"),
    ('{"stem":"看似完整"}', "length", "AI_OUTPUT_TRUNCATED"),
    (None, "stop", "AI_EMPTY_RESPONSE"),
    ("   ", "stop", "AI_EMPTY_RESPONSE"),
    ("", "content_filter", "AI_CONTENT_FILTERED"),
    (123, "stop", "AI_BAD_RESPONSE"),
])
def test_incomplete_or_empty_responses_are_not_misreported_as_invalid_json(monkeypatch, content, finish, code):
    calls, run = run_provider(monkeypatch, [(200, completion(content, finish, reasoning_content="内部思考"))])
    with pytest.raises(AppError) as caught:
        run()
    assert caught.value.code == code
    assert len(calls) == 1
    assert "内部思考" not in json.dumps(caught.value.details, ensure_ascii=False)


@pytest.mark.parametrize("status,message", [(400, "This model does not support images"), (404, "Model not found")])
def test_model_or_image_mismatch_does_not_remove_json_mode_and_retry(monkeypatch, status, message):
    calls, run = run_provider(monkeypatch, [(status, {"error": {"message": message}})])
    with pytest.raises(AppError) as caught:
        run()
    assert caught.value.code == "AI_PROVIDER_ERROR"
    assert len(calls) == 1


def test_only_explicitly_unsupported_json_mode_uses_compatibility_fallback(monkeypatch):
    calls, run = run_provider(monkeypatch, [
        (400, {"error": {"message": "response_format is not supported", "param": "response_format"}}),
        (200, completion('{"stem":"原题"}')),
    ])
    assert run().text == '{"stem":"原题"}'
    assert len(calls) == 2
    assert "response_format" not in calls[1]
    assert calls[1]["messages"] == calls[0]["messages"]


def test_content_blocks_ignore_non_text_entries(monkeypatch):
    _calls, run = run_provider(monkeypatch, [(200, completion([{"text": '{"stem":'}, {"text": None}, {"text": '"原题"}'}]))])
    assert run().text == '{"stem":"原题"}'


@pytest.mark.parametrize("task,schema,thinking,budget,body", [
    ("recognize_only", ai.Recognition, False, 8192, {"stem": "原题"}),
    ("read_supplied_answer", ai.SuppliedAnswer, False, 8192, {"answer": "用户答案"}),
    ("index_answer_page", ai.AnswerIndex, False, 16384, {"items": []}),
    ("optional_analysis", ai.Analysis, True, 32768, {"answer_draft": "1", "explanation": "推导"}),
    ("grade_printed_answers", ai.Grading, True, 32768, {"items": []}),
    ("wrong_answer_learning", ai.Analysis, True, 32768, {"answer_draft": "", "explanation": "错误原因"}),
])
def test_task_budget_and_output_schema_match_actual_learning_contract(monkeypatch, db, task, schema, thinking, budget, body):
    captured = []
    monkeypatch.setattr(ai, "configuration", lambda db: Settings(deepseek_api_key="test-key"))

    async def generate(self, request):
        captured.append(request)
        return LLMResponse(text=json.dumps(body), model="deepseek-flash")

    monkeypatch.setattr(DeepSeekProvider, "generate", generate)
    output = asyncio.run(ai.generate(db, task, "按任务处理", {}, schema))
    assert isinstance(output, schema)
    request = captured[0]
    assert request.thinking is thinking
    assert request.max_tokens == budget
    sent_schema = json.loads(request.system_prompt.split("JSON Schema：\n")[1])
    assert sent_schema == schema.model_json_schema()


def test_analysis_request_retains_reasoning_with_larger_budget(monkeypatch):
    calls, run = run_provider(monkeypatch, [(200, completion('{"answer_draft":"1","explanation":"推导"}'))],
                              LLMRequest("optional_analysis", "JSON", "原题", thinking=True, max_tokens=32768))
    run()
    assert calls[0]["thinking"] == {"type": "enabled"}
    assert calls[0]["reasoning_effort"] == "low"
    assert calls[0]["max_tokens"] == 32768


def test_invalid_region_validation_error_is_json_serializable():
    with pytest.raises(AppError) as caught:
        validate_output('{"box":[0,0,-1,1]}', ai.ImageRegion)
    assert caught.value.code == "AI_SCHEMA_INVALID"
    json.dumps(caught.value.details)


def test_json_string_example_preserves_latex_and_newlines():
    prompt = structured_prompt("只识别，不解题。", ai.Recognition)
    example = prompt.split("JSON 字符串格式示例：")[1].split("\nJSON Schema：")[0]
    assert json.loads(example) == "公式 $\\frac{1}{2}$\n下一行"
    assert prompt.startswith("只识别，不解题。")
