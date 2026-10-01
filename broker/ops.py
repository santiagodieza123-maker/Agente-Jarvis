"""Operaciones del broker. Todo se ejecuta sin shell (lista de argumentos) con salida y tiempo acotados."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from broker.protocol import ProtocolError

MAX_OUT = 8000
Runner = Callable[[list[str], float], tuple[int, str]]


def default_runner(argv: list[str], timeout: float) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, errors="replace")
    except subprocess.TimeoutExpired:
        return 124, f"tiempo agotado ({timeout:.0f} s)"
    except OSError as e:
        return 127, f"no se pudo ejecutar: {e}"
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))[-MAX_OUT:]


def winget_argv(pkg: str) -> list[str]:
    return ["winget", "install", "--id", pkg, "--exact", "--silent", "--disable-interactivity",
            "--accept-package-agreements", "--accept-source-agreements"]


def service_argv(name: str, action: str) -> list[str]:
    ps = {"start": f"Start-Service -Name '{name}'", "stop": f"Stop-Service -Name '{name}' -Force", "restart": f"Restart-Service -Name '{name}' -Force",
          "status": f"(Get-Service -Name '{name}').Status"}[action]            # `name` ya está validado (A-Za-z0-9_.-): no puede cerrar la comilla
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps]


class AllowList:
    """Servicios sobre los que el broker puede actuar. Vive en una carpeta que solo el administrador puede modificar."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def names(self) -> list[str]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return sorted({n for n in d if isinstance(n, str)}) if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def add(self, name: str) -> None:
        names = set(self.names()) | {name}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(names)), encoding="utf-8")
        os.replace(tmp, self.path)


def describe(op: str, args: dict) -> str:
    """Texto del diálogo de confirmación: qué se va a hacer, tal cual."""
    if op == "winget_install":
        return f"Instalar el paquete «{args['id']}» con winget\n\nComando: {' '.join(winget_argv(args['id']))}"
    if op == "service_control":
        return f"{args['action'].upper()} del servicio de Windows «{args['name']}»"
    if op == "allow_service":
        return f"Permitir que Jarvis controle (iniciar/detener/consultar) el servicio «{args['name']}»"
    return f"{op} {args}"


class Operations:
    def __init__(self, allow: AllowList, runner: Runner = default_runner, dry_run: bool = False, elevated: Callable[[], bool] = lambda: False):
        self.allow, self.runner, self.dry_run, self.elevated = allow, runner, dry_run, elevated

    def run(self, op: str, args: dict) -> dict:
        if op == "ping":
            return {"elevated": bool(self.elevated()), "pid": os.getpid(), "dry_run": self.dry_run}
        if op == "list_allowed":
            return {"services": self.allow.names()}
        if op == "allow_service":
            self.allow.add(args["name"])
            return {"services": self.allow.names()}
        if op == "winget_install":
            argv, timeout = winget_argv(args["id"]), 900.0
        elif op == "service_control":
            if args["name"] not in self.allow.names():
                raise ProtocolError(f"el servicio «{args['name']}» no está en la lista permitida (permítelo antes desde el HUD)")
            argv, timeout = service_argv(args["name"], args["action"]), 60.0
        else:
            raise ProtocolError(f"operación no permitida: {op!r}")
        if self.dry_run:
            return {"dry_run": True, "argv": argv}
        code, out = self.runner(argv, timeout)
        return {"exit_code": code, "output": out}
