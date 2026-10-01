"""Cliente del broker elevado (lado del núcleo, integridad Medium): firma las peticiones y las envía por la tubería con nombre."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

from broker.protocol import make_request
from core.settings import SecretStore


class BrokerError(RuntimeError):
    pass


class BrokerClient:
    def __init__(self, home: str | Path, pipe: str | None = None, transport: Callable[[str, dict, float], dict] | None = None,
                 clock: Callable[[], float] = time.time):
        self.home, self._pipe, self._transport, self.clock = Path(home), pipe, transport, clock

    @property
    def available(self) -> bool:
        return self._transport is not None or sys.platform == "win32"

    def pipe(self) -> str:
        if self._pipe:
            return self._pipe
        from broker import pipe_win
        return pipe_win.default_pipe_name()

    def _key(self) -> bytes:
        return SecretStore(self.home / "secrets.json").get_or_create_bytes("broker_key")

    def call(self, op: str, args: dict | None = None, timeout: float = 30.0) -> dict:
        """Resultado de la operación, o BrokerError (denegada, inválida, broker caído…). Bloqueante: se llama desde un hilo."""
        if not self.available:
            raise BrokerError("el broker elevado solo existe en Windows")
        transport = self._transport
        if transport is None:
            from broker import pipe_win
            transport = pipe_win.call
        try:
            resp = transport(self.pipe(), make_request(self._key(), op, args, now=self.clock()), timeout)
        except ConnectionError as e:
            raise BrokerError(str(e)) from None
        except OSError as e:
            raise BrokerError(f"fallo al hablar con el broker: {e}") from None
        if not isinstance(resp, dict) or resp.get("ok") is not True:
            raise BrokerError(str((resp or {}).get("error", "respuesta inválida del broker"))[:300])
        return resp.get("result") or {}

    def status(self) -> dict:
        if not self.available:
            return {"available": False, "running": False}
        try:
            ping = self.call("ping", timeout=3.0)
            allowed = self.call("list_allowed", timeout=3.0).get("services", [])
            return {"available": True, "running": True, "elevated": bool(ping.get("elevated")), "pid": ping.get("pid"),
                    "dry_run": bool(ping.get("dry_run")), "services": allowed, "error": ""}
        except BrokerError as e:
            return {"available": True, "running": False, "error": "" if "no está en marcha" in str(e) else str(e)}
