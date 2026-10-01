"""Punto de entrada del núcleo (lo lanza el watchdog): `python -m core.main`."""
import asyncio
import sys

from core.audit import AuditLog
from core.bus import EventBus
from core.server import HudServer


async def run() -> None:
    bus = EventBus()
    audit = AuditLog("audit/audit.jsonl")
    server = HudServer(bus, port=8765)
    port = await server.start()
    audit.append("core.started", port=port)
    # El token se entrega por stdout al lanzador del HUD; no se escribe en disco ni en logs.
    print(f"JARVIS_READY port={port} token={server.token}", flush=True)
    bus.publish("state.changed", {"state": "idle"})
    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)
