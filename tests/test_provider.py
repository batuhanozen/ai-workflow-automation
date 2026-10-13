import json

import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderError
from app.providers.openai import OpenAIProvider
from tests.test_pipeline import valid_output


def provider(handler):
    return OpenAIProvider(
        Settings(_env_file=None, openai_api_key="test-secret"), httpx.MockTransport(handler)
    )


def test_structured_output_contract(payload):
    def handler(request):
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert body["response_format"]["json_schema"]["strict"] is True
        schema = body["response_format"]["json_schema"]["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert json.loads(body["messages"][1]["content"]) == payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": valid_output(payload)}}
                ]
            },
        )

    assert provider(handler).classify(**payload) == valid_output(payload)


@pytest.mark.parametrize(
    "status,retryable",
    [(408, True), (429, True), (500, True), (503, True), (400, False), (401, False), (302, False)],
)
def test_provider_http_errors_are_safe(payload, status, retryable):
    with pytest.raises(ProviderError) as exc:
        provider(lambda r: httpx.Response(status, text="SECRET from provider")).classify(**payload)
    assert exc.value.retryable is retryable
    assert "SECRET" not in str(exc.value)


@pytest.mark.parametrize(
    "exception,code",
    [(httpx.ReadTimeout("secret"), "timeout"), (httpx.ConnectError("secret"), "connection")],
)
def test_timeout_and_connection_errors(payload, exception, code):
    def handler(request):
        raise exception

    with pytest.raises(ProviderError) as exc:
        provider(handler).classify(**payload)
    assert exc.value.code == code and exc.value.retryable
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize(
    "body,code",
    [
        ({"choices": []}, "invalid_response"),
        ({"choices": [{"message": {"refusal": "refused"}}]}, "refusal"),
        ({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}, "incomplete"),
        (
            {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
            "invalid_response",
        ),
    ],
)
def test_response_edge_cases(payload, body, code):
    with pytest.raises(ProviderError) as exc:
        provider(lambda r: httpx.Response(200, json=body)).classify(**payload)
    assert exc.value.code == code


@pytest.mark.parametrize("message", [None, [], "invalid"])
def test_non_object_message_is_invalid_response(payload, message):
    body = {"choices": [{"finish_reason": "stop", "message": message}]}
    with pytest.raises(ProviderError) as exc:
        provider(lambda r: httpx.Response(200, json=body)).classify(**payload)
    assert exc.value.code == "invalid_response"
