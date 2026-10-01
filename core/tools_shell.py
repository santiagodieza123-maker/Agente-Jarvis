"""Herramienta de shell: SIEMPRE requiere aprobación humana (clase DESTRUCTIVE), con timeout, tope de salida y entorno limpio."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from pathlib import Path

from core.orchestrator import Tool
from core.policy import ActionClass

SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


def clean_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Copia del entorno sin variables que parezcan secretos: el hijo no debe heredar la clave de Gemini."""
    return {k: v for k, v in (env or os.environ).items() if not any(m in k.upper() for m in SECRET_MARKERS)}


def _argv(command: str) -> list[str]:
    if os.name == "nt":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command]
    return ["/bin/sh", "-c", command]


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    # asyncio no da por terminado el proceso hasta que la tubería de salida llega a EOF: hay que vaciarla.
    async def drain():
        while await proc.stdout.read(65536):
            pass
    try:
        await asyncio.wait_for(drain(), 3)
        await asyncio.wait_for(proc.wait(), 3)
    except asyncio.TimeoutError:
        pass


class ShellTools:
    def __init__(self, cwd: str | Path, timeout: float = 30.0, max_output: int = 20_000):
        self.cwd, self.timeout, self.max_output = Path(cwd), timeout, max_output

    async def exec(self, command: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            *_argv(command), cwd=self.cwd, env=clean_env(),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=(os.name != "nt"))   # grupo propio: se puede matar todo el árbol
        chunks: list[bytes] = []
        size = 0
        truncated = False

        async def read():
            nonlocal size, truncated
            while True:
                b = await proc.stdout.read(4096)
                if not b:
                    return
                room = self.max_output - size
                chunks.append(b[:room]); size += min(len(b), max(room, 0))
                if len(b) > room:
                    truncated = True
                    return   # tope alcanzado: se mata el proceso (no se acumula memoria sin límite)

        timed_out = False
        try:
            await asyncio.wait_for(read(), self.timeout)
        except asyncio.TimeoutError:
            timed_out = True
        if truncated or timed_out:
            await _kill_tree(proc)
        else:
            await proc.wait()
        out = b"".join(chunks).decode("utf-8", errors="replace")
        if timed_out:
            out += f"\n[timeout tras {self.timeout:g}s: proceso terminado]"
        if truncated:
            out += f"\n[salida truncada a {self.max_output} bytes: proceso terminado]"
        return f"[exit {proc.returncode}]\n{out}"

    def tools(self) -> list[Tool]:
        return [Tool(
            "shell.exec", ActionClass.DESTRUCTIVE, self.exec,
            "Ejecuta un comando en el shell nativo (PowerShell en Windows). Requiere aprobación humana cada vez.",
            untrusted_output=True,
            parameters={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]})]
