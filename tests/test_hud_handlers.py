import asyncio
import json

from websockets.asyncio.client import connect

from core.audit import AuditLog
from core.bus import EventBus
from core.hud_handlers import HudHandlers
from core.server import HudServer


def test_panic_emits_event_audits_and_exits(tmp_path):
    codes = []

    async def go():
        bus = EventBus()
        h = HudHandlers(bus, AuditLog(tmp_path / "a.jsonl"), exit_fn=codes.append)
        srv = HudServer(bus, on_message=h)
        port = await srv.start()
        try:
            async with connect(f"ws://127.0.0.1:{port}/?token={srv.token}") as ws:
                await ws.send(json.dumps({"type": "panic"}))
                ev = json.loads(await asyncio.wait_for(ws.recv(), 2))
                assert ev["type"] == "kill.triggered"
                await asyncio.sleep(0.3)
        finally:
            await srv.stop()
    asyncio.run(go())
    assert codes == [1]
    assert AuditLog(tmp_path / "a.jsonl").verify()


def test_approval_roundtrip_and_timeout(tmp_path):
    async def go():
        h = HudHandlers(EventBus(), AuditLog(tmp_path / "a.jsonl"), exit_fn=lambda c: None)
        t = asyncio.create_task(h.request("a1", timeout=2))
        await asyncio.sleep(0.05)
        await h({"type": "approval", "id": "a1", "granted": True})
        assert await t is True
        assert await h.request("a2", timeout=0.05) is False     # sin respuesta: se deniega
    asyncio.run(go())


def test_garbage_messages_ignored(tmp_path):
    async def go():
        bus = EventBus()
        h = HudHandlers(bus, AuditLog(tmp_path / "a.jsonl"), exit_fn=lambda c: None)
        srv = HudServer(bus, on_message=h)
        port = await srv.start()
        try:
            async with connect(f"ws://127.0.0.1:{port}/?token={srv.token}") as ws:
                await ws.send("no es json"); await ws.send("[1,2]"); await ws.send(json.dumps({"type": "???"}))
                await ws.send(json.dumps({"type": "task", "goal": "hola"}))
                ev = json.loads(await asyncio.wait_for(ws.recv(), 2))
                assert ev["type"] == "plan.updated"
        finally:
            await srv.stop()
    asyncio.run(go())


def test_panic_runs_cleanup_hooks_even_if_one_fails(tmp_path):
    order = []

    async def go():
        h = HudHandlers(EventBus(), AuditLog(tmp_path / "a.jsonl"), exit_fn=lambda c: order.append("exit"))
        async def aclose(): order.append("web")
        def boom(): raise RuntimeError("x")
        h.panic_hooks = [lambda: order.append("shell"), boom, aclose]
        await h.panic()
    asyncio.run(go())
    assert order == ["shell", "web", "exit"]          # un hook roto no impide limpiar ni salir
