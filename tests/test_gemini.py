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


def test_history_uses_native_function_call_and_response_with_signature():
    msgs = [{"role": "user", "content": "borra x"},
            {"role": "assistant", "content": "", "call": {"name": "fs.delete", "args": {"path": "x"}, "signature": "SIG123"}},
            {"role": "tool", "content": "<observed untrusted>ok</observed>", "name": "fs.delete"},
            {"role": "tool", "content": "postcondición NO cumplida; replanifica"},
            {"role": "assistant", "content": "hecho"}]
    c = GeminiProvider._contents(msgs)
    assert [t["role"] for t in c] == ["user", "model", "user", "model"]
    assert c[1]["parts"] == [{"functionCall": {"name": "fs.delete", "args": {"path": "x"}}, "thoughtSignature": "SIG123"}]
    assert c[2]["parts"][0] == {"functionResponse": {"name": "fs.delete", "response": {"result": "<observed untrusted>ok</observed>"}}}
    assert c[2]["parts"][1]["text"].startswith("[resultado de herramienta]")        # el aviso va en el mismo turno de usuario
    assert c[3]["parts"] == [{"text": "hecho"}]


def test_call_without_signature_omits_the_field():
    c = GeminiProvider._contents([{"role": "assistant", "content": "", "call": {"name": "a", "args": {}, "signature": None}}])
    assert "thoughtSignature" not in c[0]["parts"][0]


def test_response_signature_is_captured():
    sent = []
    def post(url, headers, body, timeout):
        return {"candidates": [{"content": {"parts": [{"functionCall": {"name": "fs.read", "args": {"path": "a"}}, "thoughtSignature": "SIGX"}]}}]}
    r = GeminiProvider("k" * 20, post=post).generate("s", [{"role": "user", "content": "x"}], [])
    assert r.tool_calls[0].signature == "SIGX"


# ---------- cuota (429) ----------
from core.llm.gemini import MAX_QUOTA_WAIT, _retry_delay  # noqa: E402


def quota_provider(script, sleeps, waits=None):
    it = iter(script)

    def post(url, headers, body, timeout):
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v
    p = GeminiProvider("k" * 20, post=post, sleep=sleeps.append)
    p.on_wait = (lambda s, why: waits.append((s, why))) if waits is not None else None
    return p


def test_retry_delay_parsing():
    assert _retry_delay({"error": {"details": [{"@type": "x"}, {"retryDelay": "17s"}]}}) == 17.0
    assert _retry_delay({"error": {"details": [{"retryDelay": "0.5s"}]}}) == 0.5
    for bad in ({}, {"error": {}}, {"error": {"details": [{"retryDelay": "soon"}, "x", None]}}, {"error": {"details": [{"retryDelay": "1m"}]}}):
        assert _retry_delay(bad) is None


def test_429_waits_the_server_delay_and_notifies():
    sleeps, waits = [], []
    p = quota_provider([LLMError("HTTP 429: cuota", retry_after=12.0), OK], sleeps, waits)
    assert p.generate("s", [{"role": "user", "content": "x"}], []).tool_calls
    assert sleeps == [12.5] and waits == [(12.0, "cuota de Gemini")]


def test_429_without_delay_backs_off_then_gives_up_clearly():
    sleeps = []
    p = quota_provider([LLMError("HTTP 429: cuota")] * 5, sleeps)
    with pytest.raises(LLMError, match="cuota de Gemini agotada"):
        p.generate("s", [{"role": "user", "content": "x"}], [])
    assert sleeps == [5.5, 10.5, 15.5]                        # 3 reintentos con espera creciente


def test_429_with_huge_delay_fails_fast_without_sleeping():
    sleeps = []
    p = quota_provider([LLMError("HTTP 429: cuota diaria", retry_after=MAX_QUOTA_WAIT + 100)], sleeps)
    with pytest.raises(LLMError, match=r"reintenta en \d+ s"):
        p.generate("s", [{"role": "user", "content": "x"}], [])
    assert sleeps == []


def test_5xx_still_uses_short_retries_and_notifies():
    sleeps, waits = [], []
    p = quota_provider([LLMError("HTTP 503: x"), LLMError("HTTP 500: y"), OK], sleeps, waits)
    assert p.generate("s", [{"role": "user", "content": "x"}], []).tool_calls
    assert sleeps == [1, 2] and [w[1] for w in waits] == ["red o servidor"] * 2
