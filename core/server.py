"""Servidor WebSocket solo en loopback. Token por sesión y validación de Origin (anti-CSRF/DNS-rebinding)."""
from __future__ import annotations

import asyncio
import hmac
import json
import secrets
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import serve

from core.bus import EventBus

# Orígenes que usa el HUD de Tauri (WebView) y el servidor de desarrollo de Vite.
DEFAULT_ORIGINS = frozenset({"tauri://localhost", "http://tauri.localhost", "http://localhost:1420"})


MAX_MESSAGE = 8 * 1024 * 1024        # 1 MiB por defecto no basta para un fragmento de voz; sigue acotado y exige token


class HudServer:
    def __init__(self, bus: EventBus, token: str | None = None,
                 allowed_origins=DEFAULT_ORIGINS, port: int = 0, on_message=None, on_connect=None):
        self.bus = bus
        self.on_message = on_message  # callable(dict) -> None | awaitable; mensajes JSON del HUD
        self.token = token or secrets.token_urlsafe(32)
        self.allowed_origins = frozenset(allowed_origins)
        self.clients = 0                      # conexiones abiertas ahora mismo
        self.on_connect = on_connect          # se llama con cada conexión ya autenticada (p. ej. para auditarla)
        self.port = port
        self._server = None

    def _authorize(self, connection, request):
        origin = request.headers.get("Origin")
        if origin is not None and origin not in self.allowed_origins:
            return connection.respond(HTTPStatus.FORBIDDEN, "origin no permitido\n")
        host = (request.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):  # defensa contra DNS rebinding
            return connection.respond(HTTPStatus.FORBIDDEN, "host no permitido\n")
        supplied = parse_qs(urlsplit(request.path).query).get("token", [""])[0]
        if not hmac.compare_digest(supplied, self.token):
            return connection.respond(HTTPStatus.UNAUTHORIZED, "token inválido\n")
        return None

    async def _handler(self, ws) -> None:
        if self.on_connect is not None:
            self.on_connect()
        q = self.bus.subscribe()
        self.clients += 1
        try:
            async def pump():
                while True:
                    await ws.send(json.dumps(await q.get()))
            sender = asyncio.create_task(pump())
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(msg, dict) and self.on_message is not None:
                    res = self.on_message(msg)
                    if asyncio.iscoroutine(res):
                        await res
            sender.cancel()
        finally:
            self.clients -= 1
            self.bus.unsubscribe(q)

    async def start(self) -> int:
        self._server = await serve(self._handler, "127.0.0.1", self.port,
                                   process_request=self._authorize, max_size=MAX_MESSAGE)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        self._server.close()
        await self._server.wait_closed()
