"""Punto de entrada del núcleo (lo lanza el watchdog): `python -m core.main`."""
import asyncio
import contextlib
import os
import signal
import sys

from core.audit import AuditLog
from core.env import load_dotenv
from core.bus import EventBus
from core.app import FROM_CONFIG, jarvis_home, wire, workspace_roots
from core.server import HudServer


async def run() -> None:
    load_dotenv()
    bus = EventBus()
    audit = AuditLog(jarvis_home() / "audit.jsonl")
    handlers = wire(FROM_CONFIG, bus, audit, workspace_roots())
    server = HudServer(bus, port=int(os.environ.get("JARVIS_CORE_PORT", "8765")), on_message=handlers,
                       on_connect=lambda: audit.append("hud.connected"))
    port = await server.start()
    audit.append("core.started", port=port)
    handlers.extensions.start_enabled()     # las extensiones activadas arrancan en segundo plano
    # El token se entrega por stdout al lanzador del HUD; no se escribe en disco ni en logs.
    print(f"JARVIS_READY port={port} token={server.token}", flush=True)
    bus.publish("state.changed", {"state": "idle"})
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)    # cierre ordenado: que no queden hijos huérfanos
        except (NotImplementedError, RuntimeError):
            pass                                                            # Windows: el Job Object del watchdog cubre este caso
    await stop.wait()
    audit.append("core.stopped")
    await handlers.cleanup()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(server.stop(), 3)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)
