import asyncio
import json
import os
import stat
import sys
import types

import pytest

from core.app import FROM_CONFIG, wire
from core.audit import AuditLog
from core.bus import EventBus
from core.llm.gemini import GeminiProvider
from core.llm.provider import LLMProvider, LLMResponse, ToolCall
from core.settings import SecretStore, SettingsError, SettingsStore

KEY = "AQ.test-key_0123456789abcdef"


# ---------- SettingsStore ----------
def test_defaults_validation_and_persistence(tmp_path):
    p = tmp_path / "s.json"
    s = SettingsStore(p)
    assert s.values["max_steps"] == 15 and s.values["token_budget"] == 0
    assert s.update({"max_steps": 20, "accent": "ámbar"}) == {"max_steps": 20, "accent": "ámbar"}
    assert s.update({"max_steps": 20}) == {}                       # sin cambios: no escribe
    assert SettingsStore(p).values["max_steps"] == 20 and SettingsStore(p).values["accent"] == "ámbar"


@pytest.mark.parametrize("bad", [
    {"max_steps": 0}, {"max_steps": 51}, {"max_steps": True}, {"max_steps": "5"}, {"max_steps": 5.5},
    {"max_failures": 11}, {"approval_timeout": 9}, {"token_budget": -1}, {"browser_headed": 1}, {"accent": "turquesa"},
    {"model": "a/b"}, {"model": "m?x=1"}, {"model": "../x"}, {"model": ""}, {"model": "x" * 65}, {"model": 5},
    {"nope": 1}, {}, None, [],
])
def test_invalid_updates_rejected(tmp_path, bad):
    s = SettingsStore(tmp_path / "s.json")
    with pytest.raises(SettingsError):
        s.update(bad)
    assert not (tmp_path / "s.json").exists()


def test_update_is_all_or_nothing(tmp_path):
    s = SettingsStore(tmp_path / "s.json")
    with pytest.raises(SettingsError):
        s.update({"max_steps": 30, "accent": "turquesa"})
    assert s.values["max_steps"] == 15


def test_corrupt_or_invalid_saved_values_are_ignored(tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"max_steps": 999, "model": "a/b", "accent": "verde", "extra": 1}')
    s = SettingsStore(p)
    assert s.values["max_steps"] == 15 and s.values["model"] == "gemini-3.1-flash-lite" and s.values["accent"] == "verde"
    p.write_text("{no json")
    assert SettingsStore(p).values["max_steps"] == 15
    p.write_text("[1,2]")
    assert SettingsStore(p).values["max_steps"] == 15


def test_defaults_override_but_saved_wins(tmp_path):
    p = tmp_path / "s.json"
    assert SettingsStore(p, {"approval_timeout": 5.0}).values["approval_timeout"] == 5.0
    SettingsStore(p).update({"approval_timeout": 60})
    assert SettingsStore(p, {"approval_timeout": 5.0}).values["approval_timeout"] == 60


# ---------- SecretStore ----------
def test_file_backend_is_0600_and_roundtrips(tmp_path):
    s = SecretStore(tmp_path / "sec.json", keyring_mod=None)
    assert s.get() is None and s.backend == "archivo"
    s.set(f"  {KEY}  ")
    assert s.get() == KEY
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "sec.json").stat().st_mode) == 0o600
    s.clear()
    assert s.get() is None and not (tmp_path / "sec.json").exists()


@pytest.mark.parametrize("bad", ["", "corta", "a b c d e f g h i j k l m n", "x" * 300, "clave;rm -rf /xxxxxxxxx", None, 5])
def test_secret_validation(tmp_path, bad):
    with pytest.raises(SettingsError):
        SecretStore(tmp_path / "sec.json", keyring_mod=None).set(bad)
    assert not (tmp_path / "sec.json").exists()


class FakeKeyring:
    def __init__(self, fail=False):
        self.store, self.fail = {}, fail

    def set_password(self, s, n, v):
        if self.fail:
            raise RuntimeError("sin backend")
        self.store[(s, n)] = v

    def get_password(self, s, n):
        if self.fail:
            raise RuntimeError("sin backend")
        return self.store.get((s, n))

    def delete_password(self, s, n):
        self.store.pop((s, n), None)


def test_keyring_preferred_and_file_removed(tmp_path):
    kr = FakeKeyring()
    f = tmp_path / "sec.json"
    SecretStore(f, keyring_mod=None).set(KEY)               # había un archivo previo
    s = SecretStore(f, keyring_mod=kr)
    s.set(KEY + "2")
    assert s.backend == "keyring" and s.get() == KEY + "2" and not f.exists()
    s.clear()
    assert s.get() is None and kr.store == {}


def test_keyring_failure_falls_back_to_file(tmp_path):
    s = SecretStore(tmp_path / "sec.json", keyring_mod=FakeKeyring(fail=True))
    s.set(KEY)
    assert s.get() == KEY and (tmp_path / "sec.json").exists()


def test_failing_keyring_backend_is_not_used(monkeypatch):
    class FailKeyring:
        pass
    fake = types.SimpleNamespace(get_keyring=lambda: FailKeyring())
    FailKeyring.__name__ = "FailKeyring"
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert SecretStore._find_keyring() is None


# ---------- integración: wire + ConfigHandlers ----------
class Fake(LLMProvider):
    def __init__(self, *script):
        self.script, self.calls = list(script), 0

    def generate(self, system, messages, tools, image_png=None):
        self.calls += 1
        return self.script.pop(0) if self.script else LLMResponse(text="ok", input_tokens=3, output_tokens=2)


def build(tmp_path, llm, monkeypatch=None, **kw):
    if monkeypatch:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("JARVIS_GEMINI_MODEL", raising=False)
    ws = tmp_path / "ws"; ws.mkdir(parents=True, exist_ok=True)
    bus, audit = EventBus(), AuditLog(tmp_path / "a.jsonl")
    q = bus.subscribe()
    h = wire(llm, bus, audit, [ws], exit_fn=lambda c: None, home=tmp_path / "home", **kw)
    return h, bus, audit, q


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def last(q, type_):
    return [e for e in drain(q) if e["type"] == type_][-1]["payload"]


def test_snapshot_never_contains_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    h, bus, audit, q = build(tmp_path, FROM_CONFIG)
    asyncio.run(h({"type": "config.get"}))
    snap = last(q, "config.changed")
    assert KEY not in json.dumps(snap)
    assert snap["api_key"] == {"configured": True, "source": "entorno", "hint": "…cdef", "backend": snap["api_key"]["backend"]}
    assert snap["llm_ready"] is True and isinstance(h.config.holder.inner, GeminiProvider)


def test_set_api_key_swaps_provider_and_is_never_logged(tmp_path, monkeypatch):
    h, bus, audit, q = build(tmp_path, FROM_CONFIG, monkeypatch)
    assert h.config.holder.inner is None
    asyncio.run(h({"type": "config.set_api_key", "key": KEY}))
    evs = drain(q)
    assert h.config.holder.inner is not None and h.config.holder.inner._key == KEY
    assert KEY not in json.dumps(evs) and KEY not in (tmp_path / "a.jsonl").read_text()
    snap = [e for e in evs if e["type"] == "config.changed"][-1]["payload"]
    assert snap["api_key"]["source"] == "almacén" and snap["llm_ready"] is True
    assert audit.verify()
    # el almacén gana al entorno; al quitarlo vuelve a no haber clave
    asyncio.run(h({"type": "config.clear_api_key"}))
    assert h.config.holder.inner is None


def test_invalid_api_key_reports_error_and_keeps_state(tmp_path, monkeypatch):
    h, bus, audit, q = build(tmp_path, FROM_CONFIG, monkeypatch)
    asyncio.run(h({"type": "config.set_api_key", "key": "corta"}))
    evs = drain(q)
    assert any(e["type"] == "ui.notice" and e["payload"]["level"] == "error" for e in evs)
    assert h.config.holder.inner is None and not (tmp_path / "home" / "secrets.json").exists()


def test_model_change_rebuilds_provider_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    h, bus, audit, q = build(tmp_path, FROM_CONFIG)
    asyncio.run(h({"type": "config.set", "values": {"model": "gemini-x.1"}}))
    assert h.config.holder.inner.model == "gemini-x.1"
    h2, *_ = build(tmp_path, FROM_CONFIG)
    assert h2.config.holder.inner.model == "gemini-x.1"            # persistió
    ev = json.loads((tmp_path / "a.jsonl").read_text().splitlines()[-1])
    assert ev["event"] == "config.set" and ev["data"]["changed"] == {"model": "gemini-x.1"}


def test_invalid_set_leaves_everything_unchanged(tmp_path, monkeypatch):
    h, bus, audit, q = build(tmp_path, Fake(), monkeypatch)
    asyncio.run(h({"type": "config.set", "values": {"max_steps": 5, "accent": "turquesa"}}))
    assert h.config.store.values["max_steps"] == 15
    assert any(e["type"] == "ui.notice" for e in drain(q))
    assert audit.verify()


def test_explicit_llm_kept_until_config_changes_it(tmp_path, monkeypatch):
    fake = Fake()
    h, *_ = build(tmp_path, fake, monkeypatch)
    asyncio.run(h({"type": "config.set", "values": {"max_steps": 5}}))
    assert h.config.holder.inner is fake                              # solo model/clave recrean el proveedor


def test_no_key_task_explains_instead_of_crashing(tmp_path, monkeypatch):
    h, bus, audit, q = build(tmp_path, FROM_CONFIG, monkeypatch)

    async def go():
        await h({"type": "task", "goal": "hola"})
        await asyncio.sleep(0.1)
    asyncio.run(go())
    texts = [e["payload"].get("text", "") for e in drain(q) if e["type"] == "plan.updated"]
    assert any("CONFIG" in t for t in texts)


def test_max_steps_applied_hot(tmp_path, monkeypatch):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "a.txt").write_text("x")
    loop = [LLMResponse(tool_calls=[ToolCall("fs.read", {"path": str(tmp_path / "ws" / "a.txt")})])] * 6
    h, bus, audit, q = build(tmp_path, Fake(*loop), monkeypatch)

    async def go():
        await h({"type": "config.set", "values": {"max_steps": 2}})
        await h({"type": "task", "goal": "lee"})
        await h._task
    asyncio.run(go())
    lines = [json.loads(l) for l in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert [l["data"].get("reason") for l in lines if l["event"] == "task.aborted"] == ["max_steps"]
    assert [l["data"]["steps"] for l in lines if l["event"] == "task.finished"] == [2]


def test_token_budget_aborts_and_usage_is_reported(tmp_path, monkeypatch):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "a.txt").write_text("x")
    call = LLMResponse(tool_calls=[ToolCall("fs.read", {"path": str(tmp_path / "ws" / "a.txt")})], input_tokens=60, output_tokens=40)
    h, bus, audit, q = build(tmp_path, Fake(call, call, call, call), monkeypatch)

    async def go():
        await h({"type": "config.set", "values": {"token_budget": 150}})
        await h({"type": "task", "goal": "lee"})
        await h._task
    asyncio.run(go())
    lines = [json.loads(l) for l in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert [l["data"]["reason"] for l in lines if l["event"] == "task.aborted"] == ["max_tokens"]
    assert [l["data"]["tokens"] for l in lines if l["event"] == "task.finished"] == [200]   # 2 llamadas de 100
    snap = last(q, "config.changed")
    assert {k: snap["usage"][k] for k in ("calls", "input", "output")} == {"calls": 2, "input": 120, "output": 80}
    assert snap["usage"]["today"]["input"] == 120 and snap["usage"]["total"]["calls"] == 2


def test_test_llm_reports_success_and_failure_without_leaking(tmp_path, monkeypatch):
    h, bus, audit, q = build(tmp_path, Fake(), monkeypatch)
    asyncio.run(h({"type": "config.test_llm"}))
    notices = [e["payload"] for e in drain(q) if e["type"] == "ui.notice"]
    assert notices[-1]["level"] == "info" and "Conexión correcta" in notices[-1]["text"]

    class Boom(LLMProvider):
        def generate(self, *a, **k):
            raise RuntimeError("HTTP 400: clave inválida")
    h2, bus2, _, q2 = build(tmp_path / "x", Boom(), monkeypatch)
    asyncio.run(h2({"type": "config.test_llm"}))
    n = [e["payload"] for e in drain(q2) if e["type"] == "ui.notice"][-1]
    assert n["level"] == "error" and "RuntimeError" in n["text"]

    h3, bus3, _, q3 = build(tmp_path / "y", FROM_CONFIG, monkeypatch)
    asyncio.run(h3({"type": "config.test_llm"}))
    assert "No hay clave" in [e["payload"] for e in drain(q3) if e["type"] == "ui.notice"][-1]["text"]


def test_unknown_config_message_is_consumed_and_garbage_safe(tmp_path, monkeypatch):
    h, *_ = build(tmp_path, Fake(), monkeypatch)
    for m in ({"type": "config.nope"}, {"type": "config.set"}, {"type": "config.set", "values": "x"}, {"type": "config.set_api_key"}):
        asyncio.run(h(m))
    assert h.config.store.values["max_steps"] == 15


# ---------- secretos con nombre ----------
def test_named_secrets_coexist_and_clear_is_selective(tmp_path):
    s = SecretStore(tmp_path / "sec.json", keyring_mod=None)
    s.set(KEY)
    k1 = s.get_or_create_bytes("audit_hmac_key")
    assert len(k1) == 32 and s.get_or_create_bytes("audit_hmac_key") == k1            # estable entre llamadas
    assert SecretStore(tmp_path / "sec.json", keyring_mod=None).get_or_create_bytes("audit_hmac_key") == k1
    s.clear()                                                                          # quita solo la clave de Gemini
    assert s.get() is None and s.get_or_create_bytes("audit_hmac_key") == k1
    s.clear("audit_hmac_key")
    assert not (tmp_path / "sec.json").exists()


def test_named_secret_with_keyring_and_garbage_file(tmp_path):
    kr = FakeKeyring()
    s = SecretStore(tmp_path / "sec.json", keyring_mod=kr)
    k = s.get_or_create_bytes("audit_hmac_key")
    assert kr.store[("jarvis", "audit_hmac_key")] == k.hex() and not (tmp_path / "sec.json").exists()
    (tmp_path / "bad.json").write_text("[1,2]")
    assert SecretStore(tmp_path / "bad.json", keyring_mod=None).get() is None
    (tmp_path / "bad2.json").write_text('{"audit_hmac_key": "corta"}')
    assert len(SecretStore(tmp_path / "bad2.json", keyring_mod=None).get_or_create_bytes("audit_hmac_key")) == 32   # valor inválido: se regenera


def test_audit_export_over_handlers_and_validation(tmp_path, monkeypatch):
    h, bus, audit, q = build(tmp_path, Fake(), monkeypatch)
    audit.append("fs.write", path="x")
    asyncio.run(h({"type": "audit.export", "event": "fs.write"}))
    notices = [e["payload"] for e in drain(q) if e["type"] == "ui.notice"]
    assert "1 registros exportados" in notices[-1]["text"]
    files = list((tmp_path / "home" / "exports").glob("auditoria-*.jsonl"))
    assert len(files) == 1 and json.loads(files[0].read_text().splitlines()[0])["event"] == "fs.write"
    asyncio.run(h({"type": "audit.export", "event": "x" * 100}))
    assert drain(q)[-1]["payload"]["level"] == "error"
