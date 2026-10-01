#!/usr/bin/env python
"""Verificación de Jarvis en Windows. Prueba lo que NO se pudo ejecutar en Linux:
entorno, nivel de integridad, clics (SendInput) en cada monitor, watchdog (Job Object + atajo),
shell (PowerShell), servidor WebSocket, navegador y herramientas de compilación.

Uso (terminal NORMAL, no elevada, desde la raíz del repo):
    py -3.11 -m venv .venv ; .venv\\Scripts\\activate
    pip install -e ".[web]" ; playwright install chromium
    python tools/verify_windows.py

Durante ~40 s se abrirán ventanas y se moverá el cursor: no toques mouse ni teclado.
Genera verify_report.txt y verify_report.json: pégame el .txt. No incluye claves ni variables de entorno.
Opciones: --only <texto> (ejecuta solo checks cuyo nombre lo contenga), --skip <texto>.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
CHECKS: list[tuple[str, object]] = []


def check(name: str):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


# ---------------------------------------------------------------- utilidades de formato (portables)
def summarize(results: list[dict]) -> str:
    icon = {PASS: "[ OK ]", FAIL: "[FAIL]", WARN: "[WARN]", SKIP: "[SKIP]"}
    lines = [f"{icon[r['status']]} {r['name']}  ({r['seconds']:.1f}s)" for r in results]
    for r in results:
        if r["detail"]:
            lines.append(f"\n--- {r['name']} [{r['status']}]\n{r['detail']}")
    counts = {k: sum(r["status"] == k for r in results) for k in (PASS, FAIL, WARN, SKIP)}
    lines.append(f"\nRESUMEN: {counts[PASS]} OK, {counts[FAIL]} FAIL, {counts[WARN]} WARN, {counts[SKIP]} SKIP")
    return "\n".join(lines)


def run_checks(selected: list[tuple[str, object]]) -> list[dict]:
    results = []
    for name, fn in selected:
        t0 = time.time()
        print(f"... {name}", flush=True)
        try:
            status, detail = fn()
        except Exception:
            status, detail = FAIL, "EXCEPCIÓN:\n" + traceback.format_exc(limit=6)
        results.append({"name": name, "status": status, "detail": detail, "seconds": time.time() - t0})
        print(f"    -> {status}", flush=True)
    return results


# ---------------------------------------------------------------- ayudas Win32 (solo se usan en Windows)
def _win():
    import ctypes
    import ctypes.wintypes as wt
    return ctypes, wt


def pid_alive(pid: int) -> bool:
    ctypes, wt = _win()
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = wt.DWORD()
    k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


def wait_dead(pids: list[int], timeout: float = 6.0) -> list[int]:
    """Devuelve los PIDs que SIGUEN vivos tras `timeout`."""
    end = time.time() + timeout
    alive = list(pids)
    while alive and time.time() < end:
        alive = [p for p in alive if pid_alive(p)]
        time.sleep(0.1)
    return alive


def monitors() -> list[dict]:
    ctypes, wt = _win()
    user32, shcore = ctypes.WinDLL("user32"), ctypes.WinDLL("shcore")

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]
    proc_t = ctypes.WINFUNCTYPE(wt.BOOL, wt.HANDLE, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)
    out: list[dict] = []

    def cb(hmon, hdc, rect, data):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        dx, dy = wt.UINT(), wt.UINT()
        shcore.GetDpiForMonitor(hmon, 0, ctypes.byref(dx), ctypes.byref(dy))
        r = mi.rcMonitor
        out.append({"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom,
                    "primary": bool(mi.dwFlags & 1), "scale_pct": round(dx.value / 96 * 100)})
        return True

    keep = proc_t(cb)
    user32.EnumDisplayMonitors(None, None, keep, 0)
    return out


def integrity_level() -> str:
    ctypes, wt = _win()
    adv, k32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wt.HANDLE
    adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    adv.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD)]
    adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    adv.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)
    adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
    adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    tok = wt.HANDLE()
    if not adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    need = wt.DWORD()
    adv.GetTokenInformation(tok, 25, None, 0, ctypes.byref(need))  # TokenIntegrityLevel
    buf = ctypes.create_string_buffer(need.value)
    if not adv.GetTokenInformation(tok, 25, buf, need, ctypes.byref(need)):
        raise ctypes.WinError(ctypes.get_last_error())
    sid = ctypes.c_void_p.from_buffer(buf).value  # TOKEN_MANDATORY_LABEL.Label.Sid
    n = adv.GetSidSubAuthorityCount(sid).contents.value
    rid = adv.GetSidSubAuthority(sid, n - 1).contents.value
    for lo, name in ((0x4000, "System"), (0x3000, "High"), (0x2000, "Medium"), (0x1000, "Low")):
        if rid >= lo:
            return name
    return f"RID {rid:#x}"


# ---------------------------------------------------------------- comprobaciones
@check("entorno: Windows, Python y dependencias")
def c_env():
    miss = []
    for mod in ("websockets", "langgraph", "pydantic"):
        try:
            __import__(mod)
        except ImportError:
            miss.append(mod)
    info = f"{platform.platform()} | Python {platform.python_version()} {platform.architecture()[0]}"
    if miss:
        return FAIL, f"{info}\nFaltan: {', '.join(miss)}. Ejecuta: pip install -e \".[web]\""
    return PASS, info


@check("nivel de integridad del proceso (se espera Medium)")
def c_integrity():
    lvl = integrity_level()
    if lvl == "Medium":
        return PASS, "Medium"
    if lvl in ("High", "System"):
        return WARN, f"{lvl}: estás en una terminal elevada. El diseño exige Medium; repite en una terminal normal."
    return WARN, lvl


@check("monitores y escalado")
def c_monitors():
    ms = monitors()
    detail = "\n".join(f"#{i}: ({m['left']},{m['top']})-({m['right']},{m['bottom']}) escala {m['scale_pct']}%"
                       f"{' [principal]' if m['primary'] else ''}" for i, m in enumerate(ms))
    return (PASS if ms else FAIL), detail or "no se detectó ningún monitor"


@check("SendInput: clic exacto en cada monitor")
def c_click():
    import tkinter as tk

    from actuators import input_win32 as iw
    ctypes, wt = _win()
    user32 = ctypes.WinDLL("user32")
    ms = monitors()
    root = tk.Tk()
    root.attributes("-topmost", True)
    clicked: list[int] = []
    btn = tk.Button(root, text="CLIC (verificación Jarvis)", width=26, height=3, command=lambda: clicked.append(1))
    btn.pack(padx=20, pady=20)
    rows, bad = [], 0
    try:
        for i, m in enumerate(ms):
            root.geometry(f"+{m['left'] + 80}+{m['top'] + 80}")
            for _ in range(15):
                root.update()
                time.sleep(0.03)
            cx = btn.winfo_rootx() + btn.winfo_width() // 2
            cy = btn.winfo_rooty() + btn.winfo_height() // 2
            inside = m["left"] <= cx < m["right"] and m["top"] <= cy < m["bottom"]
            clicked.clear()
            iw.click(cx, cy)
            t0 = time.time()
            while not clicked and time.time() - t0 < 1.5:
                root.update()
                time.sleep(0.02)
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            off = (pt.x - cx, pt.y - cy)
            ok = bool(clicked) and inside and max(abs(off[0]), abs(off[1])) <= 2
            bad += not ok
            rows.append(f"monitor #{i} (escala {m['scale_pct']}%): objetivo=({cx},{cy}) cursor=({pt.x},{pt.y}) "
                        f"desvío={off} dentro_del_monitor={inside} clic_recibido={bool(clicked)} -> {'OK' if ok else 'FALLA'}")
    finally:
        root.destroy()
    return (FAIL if bad else PASS), "\n".join(rows)


def _agent_script(tmp: Path, pidfile: Path, behavior: str) -> Path:
    body = {
        "sleep": f"""
import os, subprocess, time
ch = subprocess.Popen(["powershell", "-NoProfile", "-Command", "Start-Sleep 120"])
open(r"{pidfile}", "w").write(f"{{os.getpid()}} {{ch.pid}}")
time.sleep(120)
""",
        "exit": f"""
import os
open(r"{pidfile}", "w").write(str(os.getpid()))
""",
    }[behavior]
    p = tmp / f"agent_{behavior}.py"
    p.write_text(body, encoding="utf-8")
    return p


def _start_watchdog(agent: Path):
    return subprocess.Popen([sys.executable, str(REPO / "watchdog" / "watchdog.py"), sys.executable, str(agent)],
                            cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _read_pids(pidfile: Path, timeout: float = 12.0) -> list[int]:
    end = time.time() + timeout
    while time.time() < end:
        if pidfile.exists() and pidfile.read_text().strip():
            return [int(x) for x in pidfile.read_text().split()]
        time.sleep(0.1)
    raise TimeoutError("el agente de prueba no arrancó (¿falla la ruta de Python?)")


@check("watchdog: Ctrl+Shift+F10 mata al agente y a sus hijos")
def c_watchdog_hotkey():
    from actuators import input_win32 as iw
    ctypes, _ = _win()
    user32 = ctypes.WinDLL("user32")
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        pidfile = tmp / "pids"
        wd = _start_watchdog(_agent_script(tmp, pidfile, "sleep"))
        try:
            pids = _read_pids(pidfile)
            time.sleep(1.5)  # tiempo para que el watchdog registre el atajo
            if wd.poll() is not None:
                return FAIL, f"el watchdog salió antes de tiempo (¿atajo ocupado?):\n{wd.stdout.read()[-600:]}"
            iw.hotkey(0x11, 0x10, 0x79)  # Ctrl+Shift+F10
            alive = wait_dead(pids)
            wd_dead = wd.wait(timeout=6) is not None
            stuck = [vk for vk in (0x11, 0x10, 0x12, 0x5B) if user32.GetAsyncKeyState(vk) & 0x8000]
            detail = f"PIDs agente/hijo: {pids}; siguen vivos: {alive}; watchdog terminó: {wd_dead}; teclas pegadas: {stuck}"
            return (PASS if not alive and not stuck else FAIL), detail
        except subprocess.TimeoutExpired:
            return FAIL, "el watchdog no terminó tras el atajo"
        finally:
            if wd.poll() is None:
                wd.kill()


@check("watchdog: cerrar el watchdog mata al agente (KILL_ON_JOB_CLOSE)")
def c_watchdog_job_close():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        pidfile = tmp / "pids"
        wd = _start_watchdog(_agent_script(tmp, pidfile, "sleep"))
        try:
            pids = _read_pids(pidfile)
            time.sleep(1.0)
            subprocess.run(["taskkill", "/F", "/PID", str(wd.pid)], capture_output=True)  # sin /T: solo el watchdog
            alive = wait_dead(pids)
            return (PASS if not alive else FAIL), f"PIDs agente/hijo: {pids}; siguen vivos tras matar al watchdog: {alive}"
        finally:
            if wd.poll() is None:
                wd.kill()
            wait_dead(pids, 1)


@check("watchdog: termina solo cuando el agente termina")
def c_watchdog_agent_exit():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        wd = _start_watchdog(_agent_script(tmp, tmp / "pid", "exit"))
        try:
            rc = wd.wait(timeout=10)
            return PASS, f"código de salida del watchdog: {rc}"
        except subprocess.TimeoutExpired:
            return FAIL, "el watchdog sigue vivo tras terminar el agente (el hilo de WM_QUIT no funcionó)"
        finally:
            if wd.poll() is None:
                wd.kill()


def _count_ps() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq powershell.exe", "/NH"], capture_output=True, text=True).stdout
    return out.lower().count("powershell.exe")


@check("shell.exec en PowerShell: salida, código, secretos y timeout")
def c_shell():
    from core.tools_shell import ShellTools
    os.environ["VERIFY_FAKE_SECRET_KEY"] = "VALOR-SECRETO-123"
    rows, ok = [], True

    async def go():
        nonlocal ok
        sh = ShellTools(tempfile.gettempdir(), timeout=30)
        out = await sh.exec("Write-Output hola")
        good = "hola" in out and out.startswith("[exit 0]")
        rows.append(f"salida/código: {'OK' if good else 'FALLA'} -> {out.strip()[:80]!r}"); ok &= good
        out = await sh.exec("exit 3")
        good = out.startswith("[exit 3]")
        rows.append(f"código de salida 3: {'OK' if good else 'FALLA'} -> {out.strip()[:60]!r}"); ok &= good
        out = await sh.exec("Write-Output ('[' + $env:VERIFY_FAKE_SECRET_KEY + ']')")
        good = "VALOR-SECRETO-123" not in out
        rows.append(f"el hijo no hereda secretos: {'OK' if good else 'FALLA (se filtró)'}"); ok &= good
        before = _count_ps()
        t0 = time.time()
        out = await ShellTools(tempfile.gettempdir(), timeout=2).exec("Start-Sleep 30")
        dt = time.time() - t0
        await asyncio.sleep(1)
        left = _count_ps() - before
        good = "timeout" in out and dt < 10 and left <= 0
        rows.append(f"timeout mata el árbol: {'OK' if good else 'FALLA'} (tardó {dt:.1f}s, powershell residuales: {left})"); ok &= good
        out = await ShellTools(tempfile.gettempdir(), max_output=500, timeout=15).exec("1..100000 | ForEach-Object { 'linea ' + $_ }")
        good = "truncada" in out and len(out) < 900
        rows.append(f"tope de salida: {'OK' if good else 'FALLA'} (len={len(out)})"); ok &= good
    asyncio.run(go())
    return (PASS if ok else FAIL), "\n".join(rows)


@check("núcleo: servidor WebSocket con token en Windows")
def c_server():
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    from core.bus import EventBus
    from core.server import HudServer
    rows, ok = [], True

    async def go():
        nonlocal ok
        bus = EventBus()
        srv = HudServer(bus)
        port = await srv.start()
        try:
            async with connect(f"ws://127.0.0.1:{port}/?token={srv.token}") as ws:
                await asyncio.sleep(0.1)
                bus.publish("state.changed", {"state": "thinking"})
                ev = json.loads(await asyncio.wait_for(ws.recv(), 3))
                good = ev["type"] == "state.changed"
                rows.append(f"evento recibido con token válido: {'OK' if good else 'FALLA'}"); ok &= good
            try:
                async with connect(f"ws://127.0.0.1:{port}/?token=malo"):
                    rows.append("token inválido: FALLA (se aceptó)"); ok = False
            except InvalidStatus as e:
                good = e.response.status_code == 401
                rows.append(f"token inválido rechazado (401): {'OK' if good else 'FALLA'}"); ok &= good
        finally:
            await srv.stop()
    asyncio.run(go())
    return (PASS if ok else FAIL), "\n".join(rows)


@check("navegador: Playwright + Chromium + bloqueo de red interna")
def c_web():
    try:
        import playwright  # noqa: F401
    except ImportError:
        return SKIP, "playwright no instalado: pip install -e \".[web]\" ; playwright install chromium"
    import http.server
    import threading

    from core.tools_web import BlockedURL, WebTools

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            self.wfile.write(b"<title>Verif</title><h1>hola desde Windows</h1><button>Pulsar</button>")
        def log_message(self, *a): pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    rows, ok = [], True

    async def go():
        nonlocal ok
        with tempfile.TemporaryDirectory() as d:
            w = WebTools(Path(d) / "profile", allowed_private=frozenset({f"127.0.0.1:{port}"}))
            try:
                snap = await w.open(f"http://127.0.0.1:{port}/")
                good = "hola desde Windows" in snap and "Pulsar" in snap
                rows.append(f"abrir y leer página: {'OK' if good else 'FALLA'}"); ok &= good
            except Exception as e:
                rows.append(f"abrir página: FALLA ({type(e).__name__}: {str(e)[:200]}). ¿Ejecutaste 'playwright install chromium'?")
                ok = False
            finally:
                await w.close()
            for url in ("http://127.0.0.1:8765/", "http://169.254.169.254/", "file:///C:/Windows/win.ini"):
                try:
                    await WebTools(Path(d) / "p2").check_url(url)
                    rows.append(f"bloqueo de {url}: FALLA (permitido)"); ok = False
                except BlockedURL:
                    rows.append(f"bloqueo de {url}: OK")
    try:
        asyncio.run(go())
    finally:
        srv.shutdown()
    return (PASS if ok else FAIL), "\n".join(rows)


@check("herramientas de compilación (Tauri) y WebView2")
def c_toolchain():
    rows = []
    for tool in ("node", "npm", "cargo", "rustc"):
        p = shutil.which(tool)
        rows.append(f"{tool}: {p or 'NO ENCONTRADO'}")
    webview = False
    try:
        import winreg
        for root, path in (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        ):
            try:
                winreg.CloseKey(winreg.OpenKey(root, path))
                webview = True
            except OSError:
                pass
    except ImportError:
        pass
    rows.append(f"WebView2 Runtime: {'instalado' if webview else 'NO DETECTADO (necesario para el HUD de Tauri)'}")
    missing = [r for r in rows if "NO " in r]
    return (WARN if missing else PASS), "\n".join(rows)


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--skip", default="")
    args = ap.parse_args()
    if os.name != "nt":
        print("Este script es solo para Windows (prueba SendInput, Job Objects, PowerShell...).")
        return 2
    import actuators.input_win32  # noqa: F401  fija Per-Monitor DPI V2 antes de crear cualquier ventana

    selected = [(n, f) for n, f in CHECKS
                if (not args.only or args.only.lower() in n.lower()) and not (args.skip and args.skip.lower() in n.lower())]
    print(f"Ejecutando {len(selected)} comprobaciones. No toques mouse ni teclado.\n")
    results = run_checks(selected)
    text = summarize(results)
    print("\n" + text)
    Path("verify_report.txt").write_text(text, encoding="utf-8")
    Path("verify_report.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nInforme guardado en verify_report.txt y verify_report.json")
    return 1 if any(r["status"] == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
