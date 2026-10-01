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


def hud_transparent() -> bool | None:
    """(Windows) ¿la ventana «Jarvis» tiene WS_EX_TRANSPARENT? None si no se encuentra la ventana."""
    import ctypes
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, "Jarvis")
    if not hwnd:
        return None
    return bool(u.GetWindowLongW(hwnd, -20) & 0x20)


def check_click_through(timeout: float = 20.0) -> tuple[bool, str]:
    """Ctrl+Shift+F9 (atajo global del HUD) activa y desactiva el click-through, sin necesidad de hacer clic en la ventana."""
    sys.path.insert(0, str(REPO))
    from actuators.input_win32 import hotkey
    VK_CONTROL, VK_SHIFT, VK_F9 = 0x11, 0x10, 0x78
    end = time.time() + timeout
    while time.time() < end and hud_transparent() is None:
        time.sleep(0.5)
    if hud_transparent() is None:
        return False, "no se encontró la ventana Jarvis"
    states = [hud_transparent()]
    for _ in range(2):
        hotkey(VK_CONTROL, VK_SHIFT, VK_F9)
        time.sleep(1.0)
        states.append(hud_transparent())
    return states == [False, True, False], f"estados de WS_EX_TRANSPARENT tras cada pulsación: {states}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hud")
    ap.add_argument("--no-watchdog", action="store_true")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--click-through", action="store_true", help="(Windows) comprueba el atajo Ctrl+Shift+F9")
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
        ct_ok, ct_msg = (True, "")
        if ok and a.click_through:
            ct_ok, ct_msg = check_click_through()
            print("click-through:", "OK" if ct_ok else "FALLA", ct_msg)
        stop.write_text("x")
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        print("hud.connected:", "SÍ" if ok else "NO")
        if not ok:
            print(out[-3000:])
        return 0 if ok and ct_ok else 1


if __name__ == "__main__":
    sys.exit(main())
