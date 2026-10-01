import asyncio
import base64
import json

import pytest

from core.app import wire
from core.audit import AuditLog
from core.bus import EventBus
from core.hud_voice import MAX_AUDIO_BYTES, MAX_PER_MINUTE
from core.llm.gemini import GeminiProvider, LLMError
from core.llm.holder import LLMHolder
from core.llm.provider import LLMProvider, LLMResponse

WAV = b"RIFF" + b"\x00" * 3000
B64 = base64.b64encode(WAV).decode()


# ---------- GeminiProvider.transcribe ----------
def test_transcribe_builds_audio_request_and_parses_text():
    seen = {}

    def post(url, headers, body, timeout):
        seen.update(url=url, body=body, headers=headers)
        return {"candidates": [{"content": {"parts": [{"text": " crea un archivo "}, {"text": "hola", "thought": True}]}}],
                "usageMetadata": {"promptTokenCount": 40, "candidatesTokenCount": 5}}
    p = GeminiProvider("k" * 20, post=post)
    r = p.transcribe(WAV, "audio/wav")
    assert r.text == "crea un archivo" and (r.input_tokens, r.output_tokens) == (40, 5)
    parts = seen["body"]["contents"][0]["parts"]
    assert parts[0]["text"].startswith("Transcribe literalmente") and parts[1]["inline_data"] == {"mime_type": "audio/wav", "data": B64}
    assert seen["url"].endswith(":generateContent") and "tools" not in seen["body"] and seen["headers"]["x-goog-api-key"] == "k" * 20


def test_transcribe_errors_and_retries():
    p = GeminiProvider("k" * 20, post=lambda *a: {"promptFeedback": {"blockReason": "X"}})
    with pytest.raises(LLMError, match="sin resultado"):
        p.transcribe(WAV, "audio/wav")
    seq = iter([LLMError("HTTP 503: x"), {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}])

    def post(*a):
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v
    assert GeminiProvider("k" * 20, post=post, sleep=lambda s: None).transcribe(WAV, "audio/wav").text == "ok"


# ---------- manejador ----------
class Fake(LLMProvider):
    def __init__(self, text="crea una nota", boom=None):
        self.text, self.boom, self.calls = text, boom, []

    def generate(self, *a, **k):
        return LLMResponse(text="x")

    def transcribe(self, audio, mime):
        self.calls.append((len(audio), mime))
        if self.boom:
            raise self.boom
        return LLMResponse(text=self.text, input_tokens=30, output_tokens=4)


def build(tmp_path, llm):
    (tmp_path / "ws").mkdir(exist_ok=True)
    bus, audit = EventBus(), AuditLog(tmp_path / "a.jsonl")
    q = bus.subscribe()
    h = wire(llm, bus, audit, [tmp_path / "ws"], exit_fn=lambda c: None, home=tmp_path / "home", gui_backend=None)
    return h, q


def out(q):
    return [e["payload"] for e in list(q._queue) if e["type"] == "voice.transcript"]


def test_transcribe_roundtrip_counts_usage_and_never_logs_audio_or_text(tmp_path):
    llm = Fake("Crea un archivo secreto-xyz")
    h, q = build(tmp_path, llm)
    asyncio.run(h({"type": "voice.transcribe", "id": "r1", "audio": B64, "mime": "audio/wav"}))
    assert out(q) == [{"id": "r1", "text": "Crea un archivo secreto-xyz", "silent": False}] and llm.calls == [(len(WAV), "audio/wav")]
    log = (tmp_path / "a.jsonl").read_text()
    assert "voice.transcribed" in log and "secreto-xyz" not in log and B64[:40] not in log
    assert h.config.holder.usage()["calls"] == 1 and h.config.holder.usage()["total"]["input"] == 30


@pytest.mark.parametrize("txt", ["[silencio]", "[Silencio]", "  ", "silencio."])
def test_silence_is_reported_as_silent(tmp_path, txt):
    h, q = build(tmp_path, Fake(txt))
    asyncio.run(h({"type": "voice.transcribe", "id": "s", "audio": B64}))
    assert out(q) == [{"id": "s", "text": "", "silent": True}]


def test_validation_rejects_bad_inputs_without_calling_the_model(tmp_path):
    llm = Fake()
    h, q = build(tmp_path, llm)
    msgs = [{"id": "a", "audio": B64, "mime": "video/mp4"}, {"id": "b", "audio": 5}, {"id": "c", "audio": "***no-base64***"},
            {"id": "d", "audio": "A" * (MAX_AUDIO_BYTES * 2)}, {"id": "e"}]
    for m in msgs:
        asyncio.run(h({"type": "voice.transcribe", **m}))
    errs = out(q)
    assert len(errs) == 5 and all("error" in e for e in errs) and llm.calls == []
    asyncio.run(h({"type": "voice.transcribe", "id": "tiny", "audio": base64.b64encode(b"x" * 10).decode()}))
    assert out(q)[-1] == {"id": "tiny", "text": "", "silent": True} and llm.calls == []          # fragmento diminuto: ni se envía
    asyncio.run(h({"type": "voice.transcribe", "id": "x" * 100, "audio": "!"}))
    assert out(q)[-1]["id"] == "?"


def test_rate_limit_per_minute(tmp_path):
    llm = Fake()
    h, q = build(tmp_path, llm)
    t = [1000.0]
    vh = next(x for x in h.extra if type(x).__name__ == "VoiceHandlers")
    vh.clock = lambda: t[0]

    async def go():
        for i in range(MAX_PER_MINUTE + 3):
            await h({"type": "voice.transcribe", "id": f"i{i}", "audio": B64})
        assert len(llm.calls) == MAX_PER_MINUTE and "demasiadas" in out(q)[-1]["error"]
        t[0] += 61
        await h({"type": "voice.transcribe", "id": "later", "audio": B64})
        assert out(q)[-1]["text"] == "crea una nota"
    asyncio.run(go())


def test_model_errors_and_missing_key_are_reported(tmp_path):
    h, q = build(tmp_path, Fake(boom=LLMError("HTTP 400: audio no soportado")))
    asyncio.run(h({"type": "voice.transcribe", "id": "e", "audio": B64}))
    assert "LLMError" in out(q)[-1]["error"] and h.config.holder.errors == 1
    (tmp_path / "x").mkdir()
    h2, q2 = build(tmp_path / "x", None)
    h2.config.holder.inner = None
    asyncio.run(h2({"type": "voice.transcribe", "id": "n", "audio": B64}))
    assert "clave" in out(q2)[-1]["error"]

    class NoVoice(LLMProvider):
        def generate(self, *a, **k): return LLMResponse(text="x")
    (tmp_path / "y").mkdir()
    h3, q3 = build(tmp_path / "y", NoVoice())
    asyncio.run(h3({"type": "voice.transcribe", "id": "v", "audio": B64}))
    assert "no transcribe" in out(q3)[-1]["error"]


def test_server_accepts_large_voice_frames():
    from websockets.asyncio.client import connect
    from core.server import HudServer

    async def go():
        got = []
        srv = HudServer(EventBus(), on_message=lambda m: got.append(len(m.get("audio", ""))))
        port = await srv.start()
        async with connect(f"ws://127.0.0.1:{port}/?token={srv.token}", max_size=None) as ws:
            await ws.send(json.dumps({"type": "voice.transcribe", "audio": "A" * (3 * 1024 * 1024)}))      # > 1 MiB por defecto
            await asyncio.sleep(0.5)
        await srv.stop()
        return got
    assert asyncio.run(go()) == [3 * 1024 * 1024]
