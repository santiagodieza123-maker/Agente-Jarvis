"""Proceso del broker elevado. Se lanza con privilegios de administrador (UAC) desde el HUD; no lo arranca el agente.

    python -m broker.service --home ~/.jarvis [--pipe NOMBRE] [--dry-run] [--insecure-auto-approve]

`--insecure-auto-approve` existe SOLO para las pruebas automáticas (CI): salta el diálogo de confirmación. El lanzador nunca lo pasa
y el broker lo anuncia en pantalla y en su registro."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from broker.ops import AllowList, Operations
from broker.protocol import Authenticator
from broker.server import BrokerCore


def data_dir() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Jarvis" / "broker"


def secure_dir(d: Path) -> None:
    """Carpeta del broker (lista permitida y registro): escritura solo para administradores y SYSTEM; los demás, solo lectura."""
    d.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(["icacls", str(d), "/inheritance:r", "/grant:r", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-545:(OI)(CI)RX"],
                       capture_output=True, check=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    ap.add_argument("--pipe")
    ap.add_argument("--dir", help="carpeta de datos del broker (por defecto %%PROGRAMDATA%%\\Jarvis\\broker)")
    ap.add_argument("--dry-run", action="store_true", help="valida y describe las operaciones sin ejecutarlas")
    ap.add_argument("--insecure-auto-approve", action="store_true", help="SOLO PRUEBAS: omite el diálogo de confirmación")
    a = ap.parse_args(argv)
    from broker import pipe_win as pw
    from core.settings import SecretStore
    key = SecretStore(Path(a.home) / "secrets.json").get_or_create_bytes("broker_key")
    d = Path(a.dir) if a.dir else data_dir()
    if pw.is_admin():                  # sin privilegios (pruebas) no se bloquea la carpeta: el propio proceso no podría escribir su registro
        secure_dir(d)
    approver = (lambda op, text: True) if a.insecure_auto_approve else pw.confirm_dialog
    if a.insecure_auto_approve:
        print("!!! MODO DE PRUEBA: el broker NO pedirá confirmación !!!", flush=True)
    core = BrokerCore(Authenticator(key), Operations(AllowList(d / "allowed_services.json"), dry_run=a.dry_run, elevated=pw.is_admin),
                      approver, d / "broker.log")
    name = a.pipe or pw.default_pipe_name()
    pw.serve(core, name, ready=lambda: print(f"BROKER_READY pipe={name} elevated={pw.is_admin()}", flush=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
