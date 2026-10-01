"""Lanzador: arranca el núcleo (bajo el watchdog en Windows) y abre el HUD con la conexión ya resuelta.

    python tools/launch.py                  # HUD de Tauri compilado
    python tools/launch.py --hud RUTA.exe   # otro binario
    python tools/launch.py --browser        # desarrollo: imprime/abre la URL del servidor de Vite
    python tools/launch.py --no-watchdog    # sin watchdog (Linux/macOS o depuración)

El puerto y el token llegan al HUD por variables de entorno del proceso hijo, nunca por argv.
Al cerrar el HUD (o con Ctrl+C) se detiene el núcleo; en Windows el Job Object del watchdog
mata además a todos sus procesos hijos.
"""
from __future__ import annotations

import argparse
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
READY = re.compile(r"^JARVIS_READY port=(\d+) token=(\S+)\s*$")
DEV_URL = "http://localhost:1420/"
HUD_NAME = "jarvis-hud.exe" if os.name == "nt" else "jarvis-hud"
SECRET_ENV = ("GEMINI_API_KEY",)


class LaunchError(RuntimeError):
    pass


def core_command(use_watchdog: bool) -> list[str]:
    return [sys.executable, "-m", "watchdog.watchdog" if use_watchdog else "core.main"]


def _spawn(cmd: list[str], **kw) -> subprocess.Popen:
    if os.name != "nt":
        kw["start_new_session"] = True  # grupo propio: permite matar también a los hijos del núcleo
    return subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"}, **kw)


def start_core(cmd: list[str], timeout: float = 30.0) -> tuple[subprocess.Popen, int, str]:
    """Lanza el núcleo y espera su línea JARVIS_READY. Tras ella, drena su salida en un hilo."""
    proc = _spawn(cmd)
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    seen: list[str] = []
    try:
        while True:
            try:
                line = lines.get(timeout=timeout)
            except queue.Empty:
                raise LaunchError(f"el núcleo no declaró JARVIS_READY en {timeout:.0f} s") from None
            if line is None:
                raise LaunchError("el núcleo terminó antes de arrancar:\n" + "".join(seen)[-2000:])
            m = READY.match(line)
            if m:
                break
            seen.append(line)
    except LaunchError:
        stop(proc)
        raise

    def drain() -> None:  # evita que el núcleo se bloquee escribiendo; nunca reenvía el token
        while (line := lines.get()) is not None:
            sys.stderr.write("[core] " + line)

    threading.Thread(target=drain, daemon=True).start()
    return proc, int(m.group(1)), m.group(2)


def stop(proc: subprocess.Popen, grace: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.terminate()  # el Job Object del watchdog mata al agente y a sus hijos al cerrarse
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=grace)
    except (subprocess.TimeoutExpired, ProcessLookupError, PermissionError):
        try:
            os.killpg(proc.pid, signal.SIGKILL) if os.name != "nt" else proc.kill()
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()


def find_hud(explicit: str | None) -> list[str] | None:
    cand = explicit or os.environ.get("JARVIS_HUD_BIN")
    if cand:
        return [cand]
    built = REPO / "hud" / "src-tauri" / "target" / "release" / HUD_NAME
    return [str(built)] if built.is_file() else None


def hud_env(port: int, token: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env.update(JARVIS_PORT=str(port), JARVIS_TOKEN=token)
    return env


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hud", help="binario del HUD (por defecto: JARVIS_HUD_BIN o el build de Tauri)")
    ap.add_argument("--browser", action="store_true", help="modo desarrollo: usa el servidor de Vite en el navegador")
    ap.add_argument("--no-watchdog", action="store_true", help="no usar el watchdog (siempre implícito fuera de Windows)")
    ap.add_argument("--timeout", type=float, default=30.0, help="segundos de espera al arranque del núcleo")
    args = ap.parse_args(argv)

    hud_cmd = None if args.browser else find_hud(args.hud)
    if not args.browser and hud_cmd is None:
        print("No hay HUD compilado. Compílalo (cd hud && npm install && npm run tauri build), indica --hud RUTA, "
              "o usa --browser con `npm run dev`.", file=sys.stderr)
        return 2

    try:
        core, port, token = start_core(core_command(os.name == "nt" and not args.no_watchdog), args.timeout)
    except LaunchError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    hud: subprocess.Popen | None = None
    try:
        if args.browser:
            url = f"{DEV_URL}?port={port}&token={token}"
            print(f"HUD (desarrollo, requiere `npm run dev` en hud/): {url}")
            webbrowser.open(url)
            core.wait()
            return 0
        hud = subprocess.Popen(hud_cmd, env=hud_env(port, token))
        return hud.wait()  # si el núcleo cae (pánico) el HUD sigue abierto mostrando KILLED
    except FileNotFoundError:
        print(f"Error: no se pudo ejecutar el HUD: {hud_cmd[0]}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if hud is not None and hud.poll() is None:
            hud.terminate()
        stop(core)


if __name__ == "__main__":
    sys.exit(run())
