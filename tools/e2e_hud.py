"""Prueba de extremo a extremo con el HUD real: lanzador -> núcleo -> HUD (Tauri) -> conexión WebSocket autenticada.
Éxito = el núcleo registra `hud.connected` en su auditoría (el HUD recibió el token por stdin y conectó).
Uso: python tools/e2e_hud.py [--hud RUTA] [--no-watchdog] [--timeout 60]   (en Linux, bajo xvfb-run)"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def connected(audit: Path) -> bool:
    try:
        return any(json.loads(l).get("event") == "hud.connected" for l in audit.read_text(encoding="utf-8").splitlines() if l.strip())
    except (OSError, ValueError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hud")
    ap.add_argument("--no-watchdog", action="store_true")
    ap.add_argument("--timeout", type=float, default=60.0)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        stop, audit = tmp / "stop", tmp / "home" / "audit.jsonl"
        env = {**os.environ, "JARVIS_HOME": str(tmp / "home"), "JARVIS_ROOTS": str(tmp / "ws"), "JARVIS_CORE_PORT": "0", "GEMINI_API_KEY": ""}
        cmd = [sys.executable, str(REPO / "tools" / "launch.py"), "--stop-file", str(stop)]
        if a.hud:
            cmd += ["--hud", a.hud]
        if a.no_watchdog:
            cmd.append("--no-watchdog")
        proc = subprocess.Popen(cmd, env=env, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        ok, end = False, time.time() + a.timeout
        while time.time() < end and proc.poll() is None:
            if connected(audit):
                ok = True
                break
            time.sleep(0.5)
        stop.write_text("x")
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        print("hud.connected:", "SÍ" if ok else "NO")
        if not ok:
            print(out[-3000:])
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
