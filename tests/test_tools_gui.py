import asyncio
import io

import pytest
from PIL import Image

from core.orchestrator import Orchestrator
from core.tools_gui import GuiResult, GuiTools, SAFE_KEYS, is_protected
from perception import som
from perception.backend import GuiError
from perception.model import Element, Snapshot, WindowInfo, diff_summary
from tests.fakes_gui import FakeBackend


def png(w=400, h=300):
    b = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(b, "PNG")
    return b.getvalue()


def app():
    be = FakeBackend()
    be.add_window(10, "Banco de Pruebas", "form.exe", [
        Element(0, "Estado: inicial", "text", (10, 10, 200, 30)),
        Element(0, "Nombre", "edit", (10, 40, 200, 70), value=""),
        Element(0, "Clave", "edit", (10, 80, 200, 110), value="", secret=True),
        Element(0, "Saludar", "button", (10, 120, 100, 150)),
        Element(0, "Aceptar", "checkbox", (10, 160, 100, 180), checked=False),
        Element(0, "Bloqueado", "button", (120, 120, 200, 150), enabled=False),
    ], rect=(0, 0, 400, 300), foreground=True)
    be.add_window(20, "Jarvis", "jarvis-hud.exe", [Element(0, "Permitir", "button", (300, 200, 390, 290))], rect=(300, 200, 400, 300))
    be.add_window(30, "Notas", "notepad.exe", [Element(0, "Editor", "document", (0, 0, 100, 100), value="hola")], rect=(0, 0, 100, 100))

    def hook(win, el):
        els = win["els"]
        if el.name == "Saludar":
            els[0].name = "Estado: Hola, " + els[1].value
        elif el.name == "Aceptar":
            el.checked = not el.checked
    be.on_activate = hook
    return be


def tools(be=None, frames=None):
    be = be or app()
    return be, GuiTools(be, on_frame=(frames.append if frames is not None else None), settle=0)


def run(c):
    return asyncio.run(c)


def test_protected_detection():
    assert is_protected(WindowInfo(1, "Jarvis", "x.exe")) and is_protected(WindowInfo(1, "otra", "jarvis-hud.exe"))
    assert is_protected(WindowInfo(1, "J.A.R.V.I.S. HUD", "msedge.exe"))
    assert not is_protected(WindowInfo(1, "Notas", "notepad.exe"))


def test_windows_hide_jarvis_hud():
    be, g = tools()
    out = run(g.windows())
    assert "Banco de Pruebas" in out and "Notas" in out and "Jarvis" not in out and "*" in out


def test_observe_numbers_elements_hides_secrets_and_picks_window():
    be, g = tools()
    r = run(g.observe())
    assert isinstance(r, GuiResult) and 'VENTANA "Banco de Pruebas"' in r
    assert '[2] edit "Nombre" valor=""' in r and '(contraseña: no accesible)' in r and "(deshabilitado)" in r and "sin marcar" in r
    assert "Notas" not in r
    assert "Editor" in run(g.observe("notas")) and "valor" in run(g.observe("notas"))
    with pytest.raises(GuiError, match="no hay ninguna ventana"):
        run(g.observe("inexistente"))
    with pytest.raises(GuiError, match="no hay ninguna ventana"):
        run(g.observe("jarvis"))                                        # el HUD no se puede ni nombrar


def test_observe_refuses_when_foreground_is_the_hud():
    be, g = tools()
    be.fg = 20
    with pytest.raises(GuiError, match="Jarvis"):
        run(g.observe())
    assert "Banco de Pruebas" in run(g.observe("banco"))               # pero una ventana concreta sí


def test_click_changes_ui_reports_diff_and_renumbers():
    be, g = tools()
    run(g.observe())
    run(g.type(2, "Ana"))
    r = run(g.click(4))
    assert "Estado: Hola, Ana" in r and "Cambios:" in r and r.ok
    assert be.log[-1] == ("activate", "Saludar")
    assert 'VENTANA "Banco de Pruebas"' in r                           # incluye la nueva observación con numeración vigente


def test_click_guards():
    be, g = tools()
    with pytest.raises(GuiError, match="no hay observación"):
        run(g.click(1))
    run(g.observe())
    with pytest.raises(GuiError, match="no existe"):
        run(g.click(99))
    for bad in (True, "1", 2.5, None):
        with pytest.raises(GuiError, match="entero"):
            run(g.click(bad))
    assert not run(g.click(6)).ok and "deshabilitado" in run(g.click(6))
    assert not run(g.click(3)).ok and "contraseña" in run(g.click(3))
    assert not [l for l in be.log if l[0] == "activate"]               # nada se activó


def test_stale_element_is_detected_by_backend():
    be, g = tools()
    run(g.observe())
    be.wins[10]["els"].pop(3)                                           # el botón desaparece entre observar y pulsar
    with pytest.raises(GuiError, match="ya no existe"):
        run(g.click(4))


def test_type_verifies_postcondition_and_refuses_wrong_targets():
    be, g = tools()
    run(g.observe())
    ok = run(g.type(2, "Hola mundo"))
    assert ok.ok and "Hola mundo" in ok
    be.truncate_typing = 3
    bad = run(g.type(2, "Hola mundo"))
    assert not bad.ok and "no lo escrito" in bad
    be.truncate_typing = None
    assert "contraseña" in run(g.type(3, "secreto")) and not [l for l in be.log if l[0] == "set_value" and l[1] == "Clave"]
    assert "no un campo de texto" in run(g.type(4, "x"))
    assert "inválido" in run(g.type(2, "x" * 3000))
    run(g.type(2, "x", submit=True))
    assert ("press", "enter") in be.log


def test_press_allowlist_focus_and_protection():
    be, g = tools()
    assert not run(g.press("tab")).ok                                   # sin observación previa
    run(g.observe())
    for bad in ("alt+f4", "win+r", "ctrl+alt+delete", "ctrl+w+x", "", "f4", "ctrl+shift+esc"):
        r = run(g.press(bad))
        assert not r.ok and "no permitida" in r, bad
    assert run(g.press("ctrl+a")).ok and ("press", "ctrl+a") in be.log
    assert run(g.press(" Ctrl + S ")).ok
    be.fg = 30
    assert "no la observada" in run(g.press("tab"))
    be.fg = 20
    assert "Jarvis" in run(g.press("enter"))
    assert not any(l == ("press", "enter") for l in be.log)             # nunca se envió Enter al HUD


def test_click_xy_limits():
    be, g = tools()
    assert not run(g.click_xy(5, 5)).ok                                  # sin observación
    run(g.observe())
    assert "fuera de la ventana" in run(g.click_xy(900, 900))
    assert "fuera de la ventana" in run(g.click_xy(True, 5))
    assert "Jarvis" in run(g.click_xy(350, 250))                         # la ventana de Jarvis está encima
    assert run(g.click_xy(50, 50)).ok and ("click_xy", 50, 50) in be.log


def test_frames_are_published_for_the_hud():
    frames = []
    be, g = tools(frames=frames)
    run(g.observe())
    run(g.click(4))
    assert len(frames) >= 3                                              # observar, resaltar el destino, tras la acción
    f = frames[0]
    assert f["image"] and f["width"] == 400 and f["elements"][3]["name"] == "Saludar" and f["title"] == "Banco de Pruebas"
    assert any(x["highlight"] == 4 and "clic" in x["action"] for x in frames)
    assert not any("Permitir" in str(x["elements"]) for x in frames)    # el HUD nunca sale en los marcos


def test_capture_failure_does_not_break_tools():
    be = app()
    def boom(rect):
        raise OSError("sin pantalla")
    be.screenshot = boom
    g = GuiTools(be, on_frame=lambda f: None, settle=0)
    r = run(g.observe(image=True))
    assert 'VENTANA "Banco' in r and "no se pudo capturar" in r and r.image is None


def test_observe_with_image_returns_annotated_png():
    be, g = tools()
    r = run(g.observe(image=True))
    assert r.image and Image.open(io.BytesIO(r.image)).size == (400, 300)


def test_tool_metadata():
    from core.policy import ActionClass as C
    ts = {t.name: t for t in tools()[1].tools()}
    assert set(ts) == {"gui.windows", "gui.observe", "gui.focus", "gui.click", "gui.type", "gui.press", "gui.click_xy"}
    assert ts["gui.windows"].cls is C.READ and ts["gui.observe"].cls is C.READ
    assert ts["gui.click"].cls is C.WRITE_REVERSIBLE and ts["gui.click_xy"].cls is C.DESTRUCTIVE
    assert all(t.untrusted_output for t in ts.values())
    assert ts["gui.click"].verify(GuiResult("x", ok=False)) is False and ts["gui.click"].verify(GuiResult("x")) is True
    assert "alt+f4" not in SAFE_KEYS and "ctrl+w" in SAFE_KEYS and "win+r" not in SAFE_KEYS


# ---------- SoM / marcos ----------
def test_annotate_draws_marks_and_downsizes():
    snap = Snapshot(1, WindowInfo(1, "t"), [Element(1, "OK", "button", (100, 100, 300, 200)), Element(2, "texto", "text", (0, 0, 50, 20))])
    base = png(3000, 1000)
    out = Image.open(io.BytesIO(som.annotate(base, snap, highlight=None)))
    assert out.size == (som.MAX_WIDTH, round(1000 * som.MAX_WIDTH / 3000))
    s = som.MAX_WIDTH / 3000
    x0 = round(100 * s)
    assert any(out.getpixel((x, round(150 * s))) != (255, 255, 255) for x in range(x0 - 2, x0 + 3))      # borde de la caja del botón (color)
    assert out.getpixel((round(10 * s), round(10 * s))) == (255, 255, 255)               # el texto no interactivo no se marca
    hl = Image.open(io.BytesIO(som.annotate(base, snap, highlight=2)))
    assert any(hl.getpixel((x, round(10 * s))) != (255, 255, 255) for x in range(round(50 * s) - 2, round(50 * s) + 3))   # el resaltado dibuja también el texto


def test_hud_frame_scales_rects_with_origin():
    snap = Snapshot(3, WindowInfo(1, "Ventana", "p.exe"), [Element(5, "A", "button", (1100, 600, 1300, 700))])
    f = som.hud_frame(png(2000, 1000), snap, origin=(100, 100), highlight=5, action="x")
    assert f["width"] == 960 and f["elements"][0]["rect"] == [480, 240, 576, 288] and f["highlight"] == 5 and f["seq"] == 3


def test_diff_summary():
    w = WindowInfo(1, "A")
    a = Snapshot(1, w, [Element(1, "x", "edit", (0, 0, 1, 1), value="a"), Element(2, "ok", "button", (0, 0, 1, 1))])
    b = Snapshot(2, w, [Element(1, "x", "edit", (0, 0, 1, 1), value="b"), Element(3, "nuevo", "button", (0, 0, 1, 1))])
    d = diff_summary(a, b)
    assert 'valor "a" -> "b"' in d and 'apareció button "nuevo"' in d and 'desapareció button "ok"' in d
    assert diff_summary(a, a) == "sin cambios visibles"
    assert "cambió la ventana" in diff_summary(a, Snapshot(3, WindowInfo(2, "B"), []))
    secret = Snapshot(2, w, [Element(1, "x", "edit", (0, 0, 1, 1), value="zzz", secret=True)])
    assert "zzz" not in diff_summary(Snapshot(1, w, [Element(1, "x", "edit", (0, 0, 1, 1), value="a", secret=True)]), secret)
