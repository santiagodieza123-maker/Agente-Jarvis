import asyncio
import json
import os

from core.llm.holder import LLMHolder
from core.llm.provider import LLMProvider, LLMResponse
from core.sysmon import SystemMonitor, llm_stats_from, parse_nvidia


def test_parse_nvidia():
    assert parse_nvidia("NVIDIA GeForce RTX 4070, 37, 1520, 12282\n") == {"name": "NVIDIA GeForce RTX 4070", "util": 37.0, "mem_used": 1520.0, "mem_total": 12282.0}
    assert parse_nvidia("A, 1, 2, 3\nB, 4, 5, 6")["name"] == "A"                       # primera GPU
    for bad in ("", "basura", "a,b,c", "x, no, 1, 2", "No devices were found"):
        assert parse_nvidia(bad) is None


def mon(**kw):
    return SystemMonitor(kw.pop("components", lambda: [{"name": "x", "state": "ok", "detail": ""}]), kw.pop("llm_stats", lambda: {"calls": 0}), **kw)


def test_sample_shape_and_sane_values():
    s = mon(gpu_query=lambda: None).sample()
    assert s["cpu"]["cores"] >= 1 and 0 <= s["cpu"]["system"] <= 100 and s["cpu"]["process"] >= 0
    assert s["memory"]["rss"] > 1_000_000 and 0 < s["memory"]["system_percent"] <= 100 and s["threads"] >= 1
    assert s["gpu"] is None and s["components"] == [{"name": "x", "state": "ok", "detail": ""}] and s["clients"] == 0
    json.dumps(s)                                                                      # serializable para el bus


def test_children_are_listed_and_cleaned(tmp_path):
    import subprocess, sys, time
    m = mon(gpu_query=lambda: None)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(0.3)
        kids = m.sample()["children"]
        assert any(k["pid"] == p.pid for k in kids) and all(set(k) == {"pid", "name", "cpu", "rss"} for k in kids)
    finally:
        p.kill(); p.wait()
    time.sleep(0.2)
    assert not any(k["pid"] == p.pid for k in m.sample()["children"])
    assert p.pid not in m._cpu_cache


def test_gpu_is_cached_between_samples():
    calls = []
    m = mon(gpu_query=lambda: calls.append(1) or "G, 10, 100, 1000", gpu_every=60)
    a, b = m.sample(), m.sample()
    assert len(calls) == 1 and a["gpu"] == b["gpu"] and a["gpu"]["util"] == 10.0
    m2 = mon(gpu_query=lambda: calls.append(1) or None, gpu_every=0)
    assert m2.sample()["gpu"] is None


def test_loop_lag_detects_a_blocked_loop():
    import time

    async def go():
        m = mon(gpu_query=lambda: None)
        await m.measure_lag()
        quiet = m.lag_ms
        async def blocker():
            await asyncio.sleep(0.01)
            time.sleep(0.2)                                                             # bloquea el bucle
        t = asyncio.create_task(blocker())
        await m.measure_lag(0.05)
        await t
        return quiet, m.lag_ms
    quiet, blocked = asyncio.run(go())
    assert quiet < 50 and blocked > 100


def test_llm_stats_from_holder():
    class L(LLMProvider):
        model = "m-test"
        def __init__(self): self.fail = False
        def generate(self, *a, **k):
            if self.fail:
                raise RuntimeError("x")
            return LLMResponse(text="x", input_tokens=1, output_tokens=1)
    l = L(); h = LLMHolder(l)
    assert llm_stats_from(h) == {"calls": 0, "errors": 0, "last_ms": None, "avg_ms": None, "p95_ms": None, "ready": True, "model": "m-test"}
    for _ in range(5):
        h.generate("s", [], [])
    l.fail = True
    try:
        h.generate("s", [], [])
    except RuntimeError:
        pass
    st = llm_stats_from(h)
    assert st["calls"] == 5 and st["errors"] == 1 and st["last_ms"] is not None and st["p95_ms"] >= 0
    assert llm_stats_from(LLMHolder(None))["ready"] is False


def test_server_counts_clients():
    from websockets.asyncio.client import connect
    from core.bus import EventBus
    from core.server import HudServer

    async def go():
        srv = HudServer(EventBus(), on_message=lambda m: None)
        port = await srv.start()
        assert srv.clients == 0
        async with connect(f"ws://127.0.0.1:{port}/?token={srv.token}") as a, connect(f"ws://127.0.0.1:{port}/?token={srv.token}") as b:
            await asyncio.sleep(0.2)
            assert srv.clients == 2
        await asyncio.sleep(0.2)
        assert srv.clients == 0
        await srv.stop()
    asyncio.run(go())


def test_components_from_wire(tmp_path):
    from core.app import wire
    from core.audit import AuditLog
    from core.bus import EventBus
    from tests.fakes_gui import FakeBackend
    (tmp_path / "ws").mkdir()
    h = wire(None, EventBus(), AuditLog(tmp_path / "a.jsonl"), [tmp_path / "ws"], exit_fn=lambda c: None, home=tmp_path / "home", gui_backend=FakeBackend())
    comps = {c["name"]: c for c in h.components()}
    assert comps["núcleo"]["state"] == "ok" and comps["navegador"]["state"] == "inactivo" and comps["UI Automation"]["state"] == "ok"
    assert comps["watchdog"]["state"] in ("ok", "aviso")
    h2 = wire(None, EventBus(), AuditLog(tmp_path / "b.jsonl"), [tmp_path / "ws"], exit_fn=lambda c: None, home=tmp_path / "home2", gui_backend=None)
    assert {c["name"]: c for c in h2.components()}["UI Automation"]["state"] == "no disponible"
