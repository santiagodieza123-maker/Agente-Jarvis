"""Protocolo del broker (sin dependencias de Windows, por lo que se prueba en cualquier sistema)."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import struct
import time
from typing import Any, Callable

VERSION = 1
MAX_FRAME = 64 * 1024
MAX_SKEW = 30.0                     # segundos de desfase admitidos entre cliente y broker
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,80}$")              # id de paquete de winget (p. ej. Microsoft.PowerToys)
SERVICE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
ACTIONS = ("start", "stop", "restart", "status")


class ProtocolError(ValueError):
    pass


def frame(obj: dict) -> bytes:
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    if len(raw) > MAX_FRAME:
        raise ProtocolError("mensaje demasiado grande")
    return struct.pack("<I", len(raw)) + raw


def unframe_length(header: bytes) -> int:
    if len(header) != 4:
        raise ProtocolError("cabecera incompleta")
    n = struct.unpack("<I", header)[0]
    if not 2 <= n <= MAX_FRAME:
        raise ProtocolError("tamaño de mensaje inválido")
    return n


def parse(raw: bytes) -> dict:
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError("JSON inválido") from None
    if not isinstance(obj, dict):
        raise ProtocolError("el mensaje debe ser un objeto")
    return obj


def sign(key: bytes, req: dict) -> str:
    body = json.dumps({k: req[k] for k in ("v", "id", "ts", "op", "args")}, separators=(",", ":"), sort_keys=True).encode()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def make_request(key: bytes, op: str, args: dict | None = None, rid: str | None = None, now: float | None = None) -> dict:
    req = {"v": VERSION, "id": rid or hashlib.sha256(f"{time.time_ns()}{op}".encode()).hexdigest()[:16], "ts": now if now is not None else time.time(),
           "op": op, "args": args or {}}
    req["mac"] = sign(key, req)
    return req


class Authenticator:
    """Comprueba firma, frescura y que el id no se repita (un mensaje capturado no se puede reenviar)."""
    def __init__(self, key: bytes, clock: Callable[[], float] = time.time):
        self.key, self.clock = key, clock
        self._seen: dict[str, float] = {}

    def check(self, req: dict) -> None:
        for k, t in (("v", int), ("id", str), ("ts", (int, float)), ("op", str), ("args", dict), ("mac", str)):
            if k not in req or isinstance(req[k], bool) or not isinstance(req[k], t):
                raise ProtocolError(f"campo inválido: {k}")
        if req["v"] != VERSION:
            raise ProtocolError("versión de protocolo no admitida")
        if not hmac.compare_digest(req["mac"], sign(self.key, req)):
            raise ProtocolError("firma inválida")
        now = self.clock()
        if abs(now - req["ts"]) > MAX_SKEW:
            raise ProtocolError("mensaje caducado")
        for rid, ts in list(self._seen.items()):
            if now - ts > 2 * MAX_SKEW:
                del self._seen[rid]
        if req["id"] in self._seen:
            raise ProtocolError("mensaje repetido")
        self._seen[req["id"]] = now


# ---------- operaciones cerradas: validación de argumentos ----------
def validate_args(op: str, args: dict) -> dict:
    """Devuelve los argumentos limpios o lanza ProtocolError. Cualquier clave no prevista se rechaza."""
    def only(allowed: set[str]) -> None:
        extra = set(args) - allowed
        if extra:
            raise ProtocolError(f"argumentos no admitidos: {sorted(extra)}")
    if op in ("ping", "shutdown", "list_allowed"):
        only(set())
        return {}
    if op == "winget_install":
        only({"id"})
        v = args.get("id")
        if not isinstance(v, str) or not ID_RE.match(v):
            raise ProtocolError("id de paquete inválido")
        return {"id": v}
    if op == "service_control":
        only({"name", "action"})
        n, a = args.get("name"), args.get("action")
        if not isinstance(n, str) or not SERVICE_RE.match(n):
            raise ProtocolError("nombre de servicio inválido")
        if a not in ACTIONS:
            raise ProtocolError(f"acción inválida; admitidas: {', '.join(ACTIONS)}")
        return {"name": n, "action": a}
    if op == "allow_service":
        only({"name"})
        n = args.get("name")
        if not isinstance(n, str) or not SERVICE_RE.match(n):
            raise ProtocolError("nombre de servicio inválido")
        return {"name": n}
    raise ProtocolError(f"operación no permitida: {op!r}")


READ_ONLY_OPS = {"ping", "shutdown", "list_allowed"}               # sin diálogo de confirmación
