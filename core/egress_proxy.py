"""Proxy HTTP/CONNECT local para el navegador del agente: cierra la ventana TOCTOU del DNS rebinding.
El navegador no resuelve nombres ni abre conexiones por su cuenta: el proxy resuelve el destino UNA vez, rechaza todo lo
que no sea una IP pública y conecta *a esa misma IP ya validada*. Cubre también subrecursos, redirecciones y WebSockets
(ws:// por HTTP y wss:// por CONNECT). El contenido de los túneles HTTPS no se inspecciona."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Awaitable, Callable
from urllib.parse import urlsplit

MAX_HEAD = 64 * 1024
HEAD_TIMEOUT = 15.0
MAX_LIFETIME = 600.0
MAX_CONNECTIONS = 64
BLOCKED_HEADER = "X-Jarvis-Blocked"


class Blocked(Exception):
    pass


def is_public(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        a = a.ipv4_mapped                       # ::ffff:127.0.0.1 es loopback aunque venga envuelto en IPv6
    return a.is_global and not a.is_multicast


async def default_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(i[4][0] for i in infos))


async def default_opener(ip: str, port: int):
    return await asyncio.open_connection(ip, port)


def split_hostport(target: str, default_port: int) -> tuple[str, int]:
    if target.startswith("["):                  # [::1]:443
        host, _, rest = target[1:].partition("]")
        if rest and not rest.startswith(":"):
            raise ValueError("destino inválido")
        port = rest[1:]
    elif target.count(":") == 1:
        host, _, port = target.partition(":")
    elif ":" in target:
        raise ValueError("IPv6 sin corchetes")
    else:
        host, port = target, ""
    if not host or (port and not port.isdigit()) or not 0 < (int(port) if port else default_port) < 65536:
        raise ValueError("destino inválido")
    return host, int(port) if port else default_port


class EgressProxy:
    def __init__(self, allowed_private: frozenset[str] = frozenset(),
                 resolver: Callable[[str, int], Awaitable[list[str]]] = default_resolver,
                 opener: Callable = default_opener, on_block: Callable[[str, str], None] | None = None):
        """`allowed_private`: 'host:puerto' permitidos aunque sean privados (solo pruebas)."""
        self.allowed_private, self.resolver, self.opener, self.on_block = allowed_private, resolver, opener, on_block
        self._server: asyncio.AbstractServer | None = None
        self._sem = asyncio.Semaphore(MAX_CONNECTIONS)
        self._tasks: set[asyncio.Task] = set()
        self.port = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server:
            self._server.close()
        for t in list(self._tasks):
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._server:
            await self._server.wait_closed()
        self._server = None

    # ---------- destino ----------
    async def dial(self, host: str, port: int):
        """Resuelve una vez, valida todas las direcciones y conecta a una de ellas (la ya validada)."""
        key = f"{host}:{port}"
        try:
            ips = [host] if _is_ip(host) else await self.resolver(host, port)
        except OSError:
            raise Blocked(f"no se pudo resolver {host}") from None
        if not ips:
            raise Blocked(f"sin direcciones para {host}")
        if key not in self.allowed_private:
            bad = [ip for ip in ips if not _safe_public(ip)]
            if bad:
                raise Blocked(f"destino interno bloqueado: {host} -> {bad[0]}")
        last: Exception | None = None
        for ip in ips:
            try:
                return await asyncio.wait_for(self.opener(ip, port), 15)
            except (OSError, asyncio.TimeoutError) as e:
                last = e
        raise Blocked(f"no se pudo conectar a {host}: {type(last).__name__}")

    # ---------- cliente ----------
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            async with self._sem:
                await asyncio.wait_for(self._serve(reader, writer), MAX_LIFETIME)
        except (asyncio.CancelledError, asyncio.TimeoutError, ConnectionError, OSError):
            pass
        finally:
            self._tasks.discard(task)
            writer.close()

    async def _deny(self, writer, host: str, reason: str) -> None:
        if self.on_block:
            self.on_block(host, reason)
        body = f"destino bloqueado: {reason}".encode()
        writer.write(b"HTTP/1.1 403 Forbidden\r\n" + f"{BLOCKED_HEADER}: 1\r\nContent-Type: text/plain; charset=utf-8\r\n".encode()
                     + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()

    async def _serve(self, reader, writer) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            return
        if len(head) > MAX_HEAD:
            return
        lines = head[:-4].decode("latin-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            return await self._bad(writer)
        try:
            if method.upper() == "CONNECT":
                host, port = split_hostport(target, 443)
                up = await self.dial(host, port)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                rest = b""
            else:
                u = urlsplit(target)
                if u.scheme != "http" or not u.hostname:
                    return await self._bad(writer)
                host, port = u.hostname, u.port or 80
                up = await self.dial(host, port)
                path = (u.path or "/") + (f"?{u.query}" if u.query else "")
                headers = [l for l in lines[1:] if l]
                upgrade = any(h.lower().startswith("upgrade:") for h in headers)
                if not upgrade:
                    headers = [h for h in headers if h.split(":", 1)[0].lower() not in ("connection", "proxy-connection", "proxy-authorization")]
                    headers.append("Connection: close")          # una sola petición por conexión: el destino validado es el único posible
                else:
                    headers = [h for h in headers if h.split(":", 1)[0].lower() not in ("proxy-connection", "proxy-authorization")]
                rest = f"{method} {path} {version}\r\n".encode("latin-1") + "\r\n".join(headers).encode("latin-1") + b"\r\n\r\n"
        except Blocked as e:
            return await self._deny(writer, target, str(e))
        except ValueError:
            return await self._bad(writer)
        ur, uw = up
        try:
            if rest:
                uw.write(rest)
                await uw.drain()
            await _pipe_both(reader, writer, ur, uw)
        finally:
            uw.close()

    @staticmethod
    async def _bad(writer) -> None:
        writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _safe_public(ip: str) -> bool:
    try:
        return is_public(ip)
    except ValueError:
        return False


async def _copy(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while data := await src.read(65536):
            dst.write(data)
            await dst.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        try:
            dst.close()
        except Exception:
            pass


async def _pipe_both(cr, cw, ur, uw) -> None:
    a = asyncio.create_task(_copy(cr, uw))
    b = asyncio.create_task(_copy(ur, cw))
    try:
        await asyncio.wait({a, b}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (a, b):
            t.cancel()
        await asyncio.gather(a, b, return_exceptions=True)
