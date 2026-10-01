"""Mensajes `broker.*` del HUD: estado, arranque (con aviso de UAC), parada y lista de servicios permitidos. El agente no puede arrancar el broker."""
from __future__ import annotations

import asyncio
from typing import Callable

from broker.protocol import SERVICE_RE
from core.bus import EventBus
from core.broker_client import BrokerClient, BrokerError


class BrokerHandlers:
    def __init__(self, bus: EventBus, audit, client: BrokerClient | None, home, start_elevated: Callable | None = None):
        self.bus, self.audit, self.client, self.home, self.start_elevated = bus, audit, client, home, start_elevated

    def _notice(self, level: str, text: str) -> None:
        self.bus.publish("ui.notice", {"level": level, "text": text})

    async def snapshot(self) -> dict:
        if self.client is None:
            return {"available": False, "running": False, "error": ""}
        return await asyncio.to_thread(self.client.status)

    async def publish(self) -> None:
        self.bus.publish("broker.changed", await self.snapshot())

    async def __call__(self, msg: dict) -> bool:
        kind = msg.get("type")
        if not isinstance(kind, str) or not kind.startswith("broker."):
            return False
        try:
            if self.client is None or not self.client.available:
                if kind != "broker.status":
                    self._notice("error", "El broker elevado solo está disponible en Windows")
            elif kind == "broker.start":
                await self._start()
            elif kind == "broker.stop":
                try:
                    await asyncio.to_thread(self.client.call, "shutdown", {}, 5.0)
                    self.audit.append("broker.stopped")
                    await asyncio.sleep(0.4)
                except BrokerError as e:
                    self._notice("error", str(e))
            elif kind == "broker.allow_service":
                name = msg.get("name")
                if not isinstance(name, str) or not SERVICE_RE.match(name):
                    self._notice("error", "nombre de servicio inválido")
                else:
                    self._notice("info", "El broker te pedirá confirmación en una ventana propia…")
                    try:
                        await asyncio.to_thread(self.client.call, "allow_service", {"name": name}, 120.0)
                        self.audit.append("broker.allow_service", name=name)
                        self._notice("info", f"Servicio «{name}» permitido")
                    except BrokerError as e:
                        self._notice("error", str(e))
            elif kind != "broker.status":
                return True
        finally:
            await self.publish()
        return True

    async def _start(self) -> None:
        st = await self.snapshot()
        if st.get("running"):
            self._notice("info", "El broker ya está en marcha")
            return
        launch = self.start_elevated
        if launch is None:
            from broker.launch import start_elevated as launch
        self.audit.append("broker.start_requested")
        ok = await asyncio.to_thread(launch, self.home)
        if not ok:
            self._notice("error", "Windows no lanzó el broker (¿rechazaste el aviso de UAC?)")
            return
        for _ in range(60):                                          # hasta ~15 s a que abra la tubería
            await asyncio.sleep(0.25)
            if (await self.snapshot()).get("running"):
                self.audit.append("broker.started")
                self._notice("info", "Broker elevado en marcha")
                return
        self._notice("error", "El broker no respondió a tiempo")
