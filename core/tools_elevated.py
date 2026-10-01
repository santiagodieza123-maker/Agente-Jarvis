"""Herramientas elevated.*: operaciones con privilegios de administrador a través del broker. Clase ELEVATED: siempre piden confirmación en
el HUD (no se puede relajar), se deniegan si la tarea leyó contenido no confiable, y el broker pide además SU propia confirmación."""
from __future__ import annotations

import asyncio

from broker.protocol import ID_RE, SERVICE_RE
from core.broker_client import BrokerClient, BrokerError
from core.orchestrator import Tool
from core.policy import ActionClass


class ElevatedResult(str):
    ok: bool = True

    def __new__(cls, text: str, ok: bool = True):
        o = super().__new__(cls, text)
        o.ok = ok
        return o


class ElevatedTools:
    def __init__(self, client: BrokerClient):
        self.client = client

    async def _call(self, op: str, args: dict, timeout: float) -> ElevatedResult:
        try:
            res = await asyncio.to_thread(self.client.call, op, args, timeout)
        except BrokerError as e:
            return ElevatedResult(f"No se realizó: {e}", False)
        if res.get("dry_run"):
            return ElevatedResult(f"(simulación) se habría ejecutado: {' '.join(res.get('argv', []))}")
        code = res.get("exit_code")
        text = f"Terminó con código {code}.\n{str(res.get('output', ''))[-1500:]}".strip()
        return ElevatedResult(text, code == 0)

    async def winget_install(self, id: str) -> ElevatedResult:
        if not isinstance(id, str) or not ID_RE.match(id):
            return ElevatedResult("Id de paquete inválido (p. ej. Microsoft.PowerToys).", False)
        return await self._call("winget_install", {"id": id}, 960.0)

    async def service(self, name: str, action: str) -> ElevatedResult:
        if not isinstance(name, str) or not SERVICE_RE.match(name):
            return ElevatedResult("Nombre de servicio inválido.", False)
        return await self._call("service_control", {"name": name, "action": action}, 90.0)

    def tools(self) -> list[Tool]:
        E = ActionClass.ELEVATED
        ver = lambda out: getattr(out, "ok", True)
        return [
            Tool("elevated.winget_install", E, self.winget_install, "Instala un programa con winget (id exacto, p. ej. Microsoft.PowerToys) con privilegios de administrador",
                 False, verify=ver, parameters={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}),
            Tool("elevated.service", E, self.service, "Inicia, detiene, reinicia o consulta un servicio de Windows de la lista permitida (action: start|stop|restart|status)",
                 False, verify=ver, parameters={"type": "object", "properties": {"name": {"type": "string"}, "action": {"type": "string"}}, "required": ["name", "action"]}),
        ]
