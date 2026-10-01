"""Arranca el broker con privilegios de administrador: Windows muestra su aviso de UAC (confirmación humana)."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def start_elevated(home: str | Path, pipe: str | None = None) -> bool:
    """True si el usuario aceptó el aviso de UAC y el proceso se lanzó. El agente nunca llama a esto: solo el HUD (mensaje broker.start)."""
    if sys.platform != "win32":
        raise OSError("el broker elevado solo existe en Windows")
    params = f'-m broker.service --home "{home}"' + (f' --pipe "{pipe}"' if pipe else "")
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, str(REPO), 0)      # SW_HIDE
    return rc > 32
