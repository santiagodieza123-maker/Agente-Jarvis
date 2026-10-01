import pytest

from core.llm.gemini import GeminiProvider, LLMError

KEY = "SECRET-KEY-123"
OK = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "fs.read", "args": {"path": "/x"}}}]}}],
      "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}}


def provider(responses, **kw):
    calls = []

    def post(url, headers, body, timeout):
        calls.append((url, headers, body))
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    return GeminiProvider(KEY, post=post, **kw), calls


def test_parses_function_call_and_usage():
    p, calls = provider([OK])
    r = p.generate("sys", [{"role": "user", "content": "hola"}], [{"name": "fs.read", "description": "d"}])
    assert r.tool_calls[0].name == "fs.read" and r.tool_calls[0].args == {"path": "/x"}
    assert (r.input_tokens, r.output_tokens) == (7, 3)
    url, headers, body = calls[0]
    assert KEY not in url and headers["x-goog-api-key"] == KEY       # la clave solo va en la cabecera
    assert url.endswith("models/gemini-3.1-flash-lite:generateContent")
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "fs.read"


def test_text_response_ignores_thought_parts():
    p, _ = provider([{"candidates": [{"content": {"parts": [{"text": "pensando", "thought": True}, {"text": "hecho"}]}}]}])
    assert p.generate("s", [{"role": "user", "content": "x"}], []).text == "hecho"


def test_history_roles_merged_and_tool_results_as_text():
    c = GeminiProvider._contents([
        {"role": "user", "content": "meta"}, {"role": "assistant", "content": "[llamada] a"},
        {"role": "tool", "content": "r1"}, {"role": "tool", "content": "r2"}])
    assert [x["role"] for x in c] == ["user", "model", "user"]
    assert len(c[2]["parts"]) == 2 and "r1" in c[2]["parts"][0]["text"]


def test_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr("core.llm.gemini.time.sleep", lambda s: None)
    p, calls = provider([LLMError("HTTP 503: x"), OK])
    assert p.generate("s", [{"role": "user", "content": "x"}], []).tool_calls
    assert len(calls) == 2


def test_no_retry_on_auth_error():
    p, calls = provider([LLMError("HTTP 403: key")])
    with pytest.raises(LLMError):
        p.generate("s", [{"role": "user", "content": "x"}], [])
    assert len(calls) == 1


def test_empty_candidates_raises():
    p, _ = provider([{"promptFeedback": {"blockReason": "SAFETY"}}])
    with pytest.raises(LLMError):
        p.generate("s", [{"role": "user", "content": "x"}], [])


def test_requires_key():
    with pytest.raises(ValueError):
        GeminiProvider("")
