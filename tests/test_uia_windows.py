"""UIABackend + GuiTools contra una aplicación WinForms real (solo Windows). En CI corre en el runner de Windows."""
import asyncio
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="UI Automation solo existe en Windows")

FIXTURE = Path(__file__).parent / "fixtures" / "winforms_app.ps1"
TITLE = "Banco de Pruebas UIA"


@pytest.fixture(scope="module")
def banco(tmp_path_factory):
    pytest.importorskip("uiautomation")
    from perception.uia import UIABackend
    log = tmp_path_factory.mktemp("banco") / "banco.log"
    proc = subprocess.Popen(["powershell.exe", "-STA", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(FIXTURE)],
                            env={**os.environ, "BANCO_LOG": str(log)}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    backend = UIABackend()
    end = time.time() + 60
    while time.time() < end:
        if any(TITLE in w.title for w in backend.run(backend.windows)):
            break
        if proc.poll() is not None:
            pytest.fail("la aplicación de pruebas terminó: " + proc.stderr.read().decode(errors="replace")[:500])
        time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("la ventana de pruebas no apareció")
    time.sleep(1.0)
    yield backend, log
    proc.kill()


def run(c):
    return asyncio.run(c)


def lines(log):
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_windows_and_observe_elements(banco):
    from core.tools_gui import GuiTools
    backend, log = banco
    g = GuiTools(backend, settle=0.6)
    assert TITLE in run(g.windows())
    t0 = time.time()
    r = run(g.observe(TITLE))
    print(f"\nobserve: {time.time() - t0:.2f}s\n{r}")
    assert f'VENTANA "{TITLE}"' in r
    assert 'button "Saludar"' in r and 'edit "Nombre"' in r and 'checkbox "Aceptar"' in r
    assert 'button "Bloqueado" (deshabilitado)' in r
    assert "contraseña: no accesible" in r and "no-leer-esto" not in r        # el campo de contraseña no se lee nunca


def test_type_click_toggle_and_diff(banco):
    from core.tools_gui import GuiTools
    backend, log = banco
    g = GuiTools(backend, settle=0.6)
    obs = run(g.observe(TITLE))
    nid = int(obs.split('edit "Nombre"')[0].rsplit("[", 1)[1].split("]")[0])
    r = run(g.type(nid, "Ana Pérez ✓"))
    assert r.ok, r
    obs = str(r)
    bid = int(obs.split('button "Saludar"')[0].rsplit("[", 1)[1].split("]")[0])
    r = run(g.click(bid))
    assert r.ok and "Estado: Hola, Ana Pérez ✓" in r, r
    assert "saludar:Ana Pérez ✓" in lines(log)                              # la aplicación realmente recibió el clic con el texto Unicode
    cid = int(str(r).split('checkbox "Aceptar"')[0].rsplit("[", 1)[1].split("]")[0])
    r = run(g.click(cid))
    assert "aceptar:True" in lines(log) and "marcado" in r


def test_secret_field_and_disabled_button_are_refused(banco):
    from core.tools_gui import GuiTools
    backend, log = banco
    g = GuiTools(backend, settle=0.3)
    obs = str(run(g.observe(TITLE)))
    pid = int(obs.split('edit "Clave"')[0].rsplit("[", 1)[1].split("]")[0])
    off = int(obs.split('button "Bloqueado"')[0].rsplit("[", 1)[1].split("]")[0])
    assert "contraseña" in run(g.type(pid, "x")) and "contraseña" in run(g.click(pid))
    assert "deshabilitado" in run(g.click(off))


def test_press_and_click_xy_and_focus(banco):
    from core.tools_gui import GuiTools
    backend, log = banco
    g = GuiTools(backend, settle=0.5)
    run(g.focus(TITLE))
    obs = str(run(g.observe(TITLE)))
    assert not run(g.press("alt+f4")).ok                                      # ni se intenta cerrar la ventana
    assert run(g.press("tab")).ok
    bid = int(obs.split('button "Saludar"')[0].rsplit("[", 1)[1].split("]")[0])
    el = g._snap.get(bid)
    before = len([l for l in lines(log) if l.startswith("saludar:")])
    r = run(g.click_xy(*el.center))
    assert r.ok
    time.sleep(0.5)
    assert len([l for l in lines(log) if l.startswith("saludar:")]) == before + 1       # el clic por coordenadas llegó de verdad
    assert "fuera de la ventana" in run(g.click_xy(-5000, -5000))


def test_screenshot_and_marks(banco):
    from PIL import Image
    from core.tools_gui import GuiTools
    backend, log = banco
    g = GuiTools(backend, settle=0.2)
    r = run(g.observe(TITLE, image=True))
    assert r.image
    img = Image.open(io.BytesIO(r.image))
    assert img.width >= 300 and img.height >= 200
    colors = {c for _, c in img.getcolors(maxcolors=1_000_000) or []}
    assert len(colors) > 5                                                     # no es una imagen en blanco: hay contenido y marcas


def test_stale_snapshot_is_rejected(banco):
    from core.tools_gui import GuiTools
    from perception.backend import GuiError
    backend, log = banco
    g = GuiTools(backend, settle=0.1)
    run(g.observe(TITLE))
    first_seq = g._snap.seq
    for _ in range(8):                                                          # el backend conserva solo las últimas observaciones
        run(g.observe(TITLE))
    with pytest.raises(GuiError, match="obsoleta"):
        backend.run(backend.activate, first_seq, 1)
