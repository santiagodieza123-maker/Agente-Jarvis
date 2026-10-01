"""Extensiones: servidores MCP por stdio, expuestos como herramientas `mcp.<ext>.<tool>`.
Un servidor MCP es código externo: solo el HUD puede darlo de alta, sus herramientas piden confirmación por defecto
(clase DESTRUCTIVE) y su salida se marca como no confiable. Todo lo que declara el servidor se sanea antes de llegar al LLM."""
from __future__ import annotations

import asyncio
import json
import re
import shlex
import shutil
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.orchestrator import Tool
from core.policy import ActionClass
from core.settings import _atomic_write

MAX_EXTENSIONS, MAX_TOOLS, MAX_OUTPUT = 16, 64, 20_000
CALL_TIMEOUT, START_TIMEOUT, PING_EVERY = 60.0, 20.0, 5.0
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")
_PROP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_TYPES = {"string", "number", "integer", "boolean", "array", "object"}
_CTRL = re.compile(r"[\x00-\x1f\x7f]+")
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_ENV_VARS, MAX_ENV_JSON = 16, 2000        # el Credential Manager de Windows admite ~2,5 KB por entrada


class ExtensionError(ValueError):
    pass


def one_line(text, limit: int) -> str:
    return _CTRL.sub(" ", str(text or "")).strip()[:limit]


def first_line(text, limit: int) -> str:
    """Solo la primera línea no vacía: lo que viene después de un salto de línea es donde suelen esconderse las instrucciones."""
    lines = [l for l in str(text or "").splitlines() if l.strip()]
    return one_line(lines[0] if lines else "", limit)


def parse_env(env) -> dict[str, str]:
    """Variables de entorno de una extensión (p. ej. un token). Se guardan en el almacén de secretos, nunca en extensions.json."""
    if env in (None, {}):
        return {}
    if not isinstance(env, dict) or len(env) > MAX_ENV_VARS:
        raise ExtensionError(f"variables de entorno inválidas (máx. {MAX_ENV_VARS})")
    out = {}
    for k, v in env.items():
        if not (isinstance(k, str) and ENV_NAME.match(k) and isinstance(v, str) and 0 < len(v) <= 500 and "\x00" not in v):
            raise ExtensionError(f"variable inválida: {str(k)[:40]} (nombre A-Z0-9_, valor de 1 a 500 caracteres)")
        out[k] = v
    if len(json.dumps(out)) > MAX_ENV_JSON:
        raise ExtensionError(f"variables demasiado largas en total (máx. {MAX_ENV_JSON} caracteres)")
    return out


def parse_cmdline(line, nt: bool | None = None) -> list[str]:
    import os
    nt = (os.name == "nt") if nt is None else nt
    if not isinstance(line, str) or not line.strip() or len(line) > 1000 or "\x00" in line or "\n" in line:
        raise ExtensionError("línea de comandos inválida (vacía, con saltos de línea o de más de 1000 caracteres)")
    try:
        argv = shlex.split(line, posix=not nt)
    except ValueError as e:
        raise ExtensionError(f"comillas sin cerrar: {e}") from None
    if nt:
        argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] and a[0] in "\"'" else a for a in argv]
    if not argv or len(argv) > 32 or any(not a or len(a) > 500 for a in argv):
        raise ExtensionError("comando vacío, con más de 32 argumentos o argumentos de más de 500 caracteres")
    return argv


def sanitize_schema(schema, depth: int = 0) -> dict | None:
    """Lista blanca del JSON Schema que declara el servidor (no confiable) al subconjunto que entiende el LLM."""
    if not isinstance(schema, dict):
        return None
    if depth >= 6:
        return {"type": "string"}
    alts = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(alts, list):
        alt = next((a for a in alts if isinstance(a, dict) and a.get("type") not in (None, "null")), None)
        if alt is not None:
            return sanitize_schema({**alt, "description": alt.get("description", schema.get("description"))}, depth)
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x in _TYPES), None)
    out: dict = {"type": t if t in _TYPES else "string"}
    if schema.get("description"):
        out["description"] = one_line(schema["description"], 200)
    enum = schema.get("enum")
    if isinstance(enum, list) and out["type"] in ("string", "number", "integer", "boolean"):
        vals = [v for v in enum[:50] if isinstance(v, (str, int, float))]
        if vals:
            out["enum"] = [one_line(v, 100) if isinstance(v, str) else v for v in vals]
    if out["type"] == "array":
        out["items"] = sanitize_schema(schema.get("items"), depth + 1) or {"type": "string"}
    if out["type"] == "object":
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        clean = {}
        for k, v in list(props.items())[:30]:
            if isinstance(k, str) and _PROP_RE.match(k):
                sub = sanitize_schema(v, depth + 1)
                if sub:
                    clean[k] = sub
        out["properties"] = clean
        req = [r for r in (schema.get("required") or []) if isinstance(r, str) and r in clean]
        if req:
            out["required"] = req
    return out


def tool_schema(input_schema) -> dict | None:
    s = sanitize_schema(input_schema)
    return s if s and s.get("type") == "object" and s.get("properties") else None   # sin parámetros: se omite


def tool_name(ext: str, raw, taken: set[str]) -> str | None:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", str(raw)).strip("_")[:40]
    if not base:
        return None
    name, n = base, 2
    while name in taken:
        name, n = f"{base[:36]}_{n}", n + 1
    taken.add(name)
    return name


def _attr(obj, *names):
    """mcp 1.x usa camelCase (inputSchema, isError) y 2.x snake_case (input_schema, is_error)."""
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return None


def render_result(res) -> str:
    parts = []
    for c in getattr(res, "content", None) or []:
        text = getattr(c, "text", None)
        parts.append(text if isinstance(text, str) else f"[contenido {getattr(c, 'type', '?')} omitido]")
    structured = _attr(res, "structuredContent", "structured_content")
    if not parts and structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False, default=str))
    text = "\n".join(parts) or "(sin contenido)"
    if _attr(res, "isError", "is_error"):
        text = "[la herramienta devolvió un error] " + text      # sigue siendo salida no confiable, no una excepción
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + f"\n[recortado: {len(text)} caracteres]"


def _explain(e: BaseException) -> str:
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    return one_line(f"{type(e).__name__}: {e}", 300)


@dataclass
class Extension:
    name: str
    argv: list[str]
    enabled: bool = True
    trusted: set[str] = field(default_factory=set)       # herramientas que el usuario marcó como solo lectura
    state: str = "stopped"                                # stopped | starting | running | error
    error: str = ""
    tools: dict[str, str] = field(default_factory=dict)   # nombre completo -> nombre original
    session: object = None
    task: asyncio.Task | None = None
    stop: asyncio.Event | None = None


class ExtensionManager:
    def __init__(self, path: str | Path, tools: dict[str, Tool], audit, notify: Callable[[], None],
                 disabled: Callable[[], set], cwd: Path, log_dir: str | Path, secrets=None):
        self.path, self.tools, self.audit, self.notify, self.disabled = Path(path), tools, audit, notify, disabled
        self.secrets = secrets
        self.cwd, self.log_dir = Path(cwd), Path(log_dir)
        self.exts: dict[str, Extension] = {}
        self._load()

    # ---------- persistencia ----------
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in (data.get("extensions") if isinstance(data, dict) else None) or []:
            try:
                name, argv = d["name"], d["argv"]
                if not (isinstance(name, str) and NAME_RE.match(name) and isinstance(argv, list) and argv
                        and all(isinstance(a, str) and 0 < len(a) <= 500 for a in argv)) or name in self.exts:
                    continue
                self.exts[name] = Extension(name, argv, d.get("enabled") is True,
                                            {t for t in d.get("trusted", []) if isinstance(t, str)})
            except (KeyError, TypeError):
                continue
            if len(self.exts) >= MAX_EXTENSIONS:
                break

    def _save(self) -> None:
        data = {"extensions": [{"name": e.name, "argv": e.argv, "enabled": e.enabled, "trusted": sorted(e.trusted)}
                               for e in self.exts.values()]}
        _atomic_write(self.path, json.dumps(data, indent=2, ensure_ascii=False))

    def _get(self, name) -> Extension:
        if not isinstance(name, str) or name not in self.exts:
            raise ExtensionError("extensión desconocida")
        return self.exts[name]

    # ---------- variables de entorno (secretas) ----------
    @staticmethod
    def _env_key(name: str) -> str:
        return f"ext_env_{name}"

    def _env(self, name: str) -> dict[str, str]:
        if self.secrets is None:
            return {}
        try:
            d = json.loads(self.secrets.get(self._env_key(name)) or "{}")
            return parse_env(d)
        except (ValueError, ExtensionError):
            return {}

    def _store_env(self, name: str, env: dict[str, str]) -> None:
        if self.secrets is None:
            if env:
                raise ExtensionError("no hay almacén de secretos disponible para las variables de entorno")
            return
        if env:
            self.secrets.set(json.dumps(env), name=self._env_key(name))
        else:
            self.secrets.clear(self._env_key(name))

    async def set_env(self, name, env) -> None:
        ext = self._get(name)
        clean = parse_env(env)
        self._store_env(name, clean)
        self.audit.append("ext.env", name=name, vars=sorted(clean))          # solo los nombres, nunca los valores
        if ext.enabled:
            await self.restart(name)
        else:
            self.notify()

    # ---------- altas y bajas ----------
    async def add(self, name, command_line, env=None) -> None:
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ExtensionError("nombre inválido: minúsculas, números, '-' y '_', empezando por letra (máx. 24)")
        if name in self.exts:
            raise ExtensionError("ya existe una extensión con ese nombre")
        if len(self.exts) >= MAX_EXTENSIONS:
            raise ExtensionError(f"máximo {MAX_EXTENSIONS} extensiones")
        argv = parse_cmdline(command_line)
        clean_env = parse_env(env)
        if shutil.which(argv[0]) is None:
            raise ExtensionError(f"no se encontró el ejecutable: {argv[0]}")
        self._store_env(name, clean_env)
        self.exts[name] = Extension(name, argv)
        self._save()
        self.audit.append("ext.add", name=name, argv=argv, env=sorted(clean_env))
        self.start(name)

    async def remove(self, name) -> None:
        ext = self._get(name)
        await self._stop(ext)
        del self.exts[name]
        self._save()
        self._store_env(name, {})
        with suppress(OSError):
            self._log_path(name).unlink()
        self.audit.append("ext.remove", name=name)

    async def set_enabled(self, name, enabled) -> None:
        ext = self._get(name)
        if not isinstance(enabled, bool):
            raise ExtensionError("valor inválido")
        ext.enabled = enabled
        self._save()
        self.audit.append("ext.enable" if enabled else "ext.disable", name=name)
        if enabled:
            self.start(name)
        else:
            await self._stop(ext)

    async def restart(self, name) -> None:
        ext = self._get(name)
        await self._stop(ext)
        self.audit.append("ext.restart", name=name)
        ext.enabled = True
        self._save()
        self.start(name)

    def set_trust(self, name, tool, read) -> None:
        ext = self._get(name)
        if not isinstance(read, bool) or not isinstance(tool, str):
            raise ExtensionError("valor inválido")
        full = next((f for f, raw in ext.tools.items() if raw == tool), None)
        if full is None and tool not in ext.trusted:
            raise ExtensionError("herramienta desconocida")
        (ext.trusted.add if read else ext.trusted.discard)(tool)
        if full:
            self.tools[full].cls = ActionClass.READ if read else ActionClass.DESTRUCTIVE
        self._save()
        self.audit.append("ext.trust", name=name, tool=tool, read=read)

    def set_tool_enabled(self, name, tool, enabled, perms) -> None:
        ext = self._get(name)
        full = next((f for f, raw in ext.tools.items() if raw == tool), None)
        if full is None:
            raise ExtensionError("herramienta desconocida")
        perms.set_tool(full, enabled)

    # ---------- ciclo de vida ----------
    def _log_path(self, name: str) -> Path:
        return self.log_dir / f"{name}.log"

    def start_enabled(self) -> None:
        for e in self.exts.values():
            if e.enabled:
                self.start(e.name)

    def start(self, name: str) -> None:
        ext = self.exts[name]
        if ext.task and not ext.task.done():
            return
        ext.stop = asyncio.Event()
        ext.state, ext.error = "starting", ""
        ext.task = asyncio.create_task(self._run(ext), name=f"ext-{name}")
        self.notify()

    async def _run(self, ext: Extension) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = open(self._log_path(ext.name), "w", encoding="utf-8", errors="replace")
        try:
            params = StdioServerParameters(command=ext.argv[0], args=ext.argv[1:], cwd=str(self.cwd), env=self._env(ext.name) or None)
            async with stdio_client(params, errlog=log) as (r, w):
                async with ClientSession(r, w) as sess:
                    await asyncio.wait_for(sess.initialize(), START_TIMEOUT)
                    listed = await asyncio.wait_for(sess.list_tools(), START_TIMEOUT)
                    ext.session = sess
                    self._register(ext, listed.tools)
                    ext.state = "running"
                    self.audit.append("ext.started", name=ext.name, tools=len(ext.tools))
                    self.notify()
                    while not ext.stop.is_set():
                        try:
                            await asyncio.wait_for(ext.stop.wait(), PING_EVERY)
                        except asyncio.TimeoutError:
                            await asyncio.wait_for(sess.send_ping(), PING_EVERY)    # detecta un servidor muerto o colgado
            ext.state = "stopped"
        except asyncio.CancelledError:
            ext.state = "stopped"
        except BaseException as e:  # noqa: BLE001 — cualquier fallo del servidor queda como estado, no tumba el núcleo
            ext.state, ext.error = "error", _explain(e)
            self.audit.append("ext.error", name=ext.name, error=ext.error)
        finally:
            ext.session = None
            self._unregister(ext)
            log.close()
            self.notify()

    def _register(self, ext: Extension, listed) -> None:
        taken: set[str] = set()
        for t in list(listed)[:MAX_TOOLS]:
            raw = getattr(t, "name", None)
            short = tool_name(ext.name, raw, taken)
            if short is None:
                continue
            full = f"mcp.{ext.name}.{short}"
            desc = f"[externa:{ext.name}] " + first_line(getattr(t, "description", "") or raw, 160)
            ext.tools[full] = raw
            self.tools[full] = Tool(full, ActionClass.READ if raw in ext.trusted else ActionClass.DESTRUCTIVE,
                                    self._runner(ext, raw), desc[:200], untrusted_output=True,
                                    parameters=tool_schema(_attr(t, "inputSchema", "input_schema")))

    def _unregister(self, ext: Extension) -> None:
        for full in ext.tools:
            self.tools.pop(full, None)
        ext.tools.clear()

    def _runner(self, ext: Extension, raw: str):
        async def run(**kw):
            sess = ext.session
            if ext.state != "running" or sess is None:
                raise ExtensionError(f"la extensión {ext.name} no está en marcha")
            try:
                res = await asyncio.wait_for(sess.call_tool(raw, kw), CALL_TIMEOUT)
            except asyncio.TimeoutError:
                raise ExtensionError(f"la herramienta tardó más de {CALL_TIMEOUT:.0f} s") from None
            return render_result(res)
        return run

    async def _stop(self, ext: Extension, timeout: float = 5.0) -> None:
        task = ext.task
        if task is None or task.done():
            ext.state = "stopped" if ext.state != "error" else ext.state
            return
        ext.stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
            with suppress(BaseException):
                await task
        except BaseException:
            pass

    async def stop_all(self) -> None:
        """Gancho de pánico: termina todos los servidores (los hijos mueren con su contexto stdio)."""
        for e in self.exts.values():
            if e.stop:
                e.stop.set()
        tasks = [e.task for e in self.exts.values() if e.task and not e.task.done()]
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=1.5)
            for t in pending:
                t.cancel()

    # ---------- vista para el HUD ----------
    def _log_tail(self, name: str) -> str:
        try:
            data = self._log_path(name).read_bytes()[-3000:]
        except OSError:
            return ""
        return data.decode("utf-8", "replace")

    def snapshot(self) -> dict:
        off = self.disabled()
        return {"extensions": [{
            "name": e.name, "command": " ".join(e.argv), "enabled": e.enabled, "state": e.state, "error": e.error,
            "env_names": sorted(self._env(e.name)),
            "tools": [{"name": full, "raw": raw, "description": self.tools[full].description if full in self.tools else "",
                       "trusted": raw in e.trusted, "enabled": full not in off} for full, raw in e.tools.items()],
            "log": self._log_tail(e.name),
        } for e in self.exts.values()], "limits": {"extensions": MAX_EXTENSIONS, "tools": MAX_TOOLS}}
