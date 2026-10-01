import asyncio
import json
import os
import shlex
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

import core.mcp_client as M
from core.app import wire
from core.audit import AuditLog
from core.bus import EventBus
from core.llm.provider import LLMProvider, LLMResponse, ToolCall
from core.policy import ActionClass as C
from tests.helpers import pid_alive

SERVER = str(Path(__file__).parent / "fixtures" / "echo_server.py")


def cmd(pidfile=None, *extra):
    return " ".join(shlex.quote(x) for x in [sys.executable, SERVER, *(([str(pidfile)] if pidfile else []) + list(extra))])


alive = pid_alive


async def wait_for(pred, t=15.0):
    end = time.time() + t
    while time.time() < end:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return False


# ---------- funciones puras ----------
def test_parse_cmdline():
    assert M.parse_cmdline('npx -y "@x/server fs" /tmp', nt=False) == ["npx", "-y", "@x/server fs", "/tmp"]
    assert M.parse_cmdline('"C:\\Program Files\\n\\node.exe" srv.js', nt=True) == ["C:\\Program Files\\n\\node.exe", "srv.js"]
    for bad in ["", "   ", "a\nb", "a\x00b", "x" * 1001, 'a "b', 5, None, " ".join(["a"] * 40), "a " + "b" * 501]:
        with pytest.raises(M.ExtensionError):
            M.parse_cmdline(bad, nt=False)


def test_sanitize_schema_whitelists_and_bounds():
    raw = {"type": "object", "$schema": "x", "additionalProperties": False, "title": "T",
           "properties": {"a": {"type": ["integer", "null"], "description": "uno\n\ndos" + "z" * 500, "default": 1},
                          "b": {"anyOf": [{"type": "null"}, {"type": "string", "enum": ["x", "y"]}]},
                          "c": {"$ref": "#/defs/c"}, "bad name!": {"type": "string"},
                          "d": {"type": "array", "items": {"type": "number"}}},
           "required": ["a", "ghost"]}
    s = M.sanitize_schema(raw)
    assert set(s) == {"type", "properties", "required"} and s["required"] == ["a"]
    assert s["properties"]["a"]["type"] == "integer" and "\n" not in s["properties"]["a"]["description"] and len(s["properties"]["a"]["description"]) <= 200
    assert "default" not in s["properties"]["a"]
    assert s["properties"]["b"] == {"type": "string", "enum": ["x", "y"]}
    assert s["properties"]["c"] == {"type": "string"} and "bad name!" not in s["properties"]
    assert s["properties"]["d"]["items"] == {"type": "number"}
    deep = {"type": "object", "properties": {}}
    cur = deep
    for _ in range(10):
        nxt = {"type": "object", "properties": {}}
        cur["properties"]["n"] = nxt
        cur = nxt
    assert json.dumps(M.sanitize_schema(deep)).count('"object"') <= 6
    assert M.sanitize_schema("x") is None and M.tool_schema({"type": "object", "properties": {}}) is None
    assert len(M.sanitize_schema({"type": "object", "properties": {f"p{i}": {"type": "string"} for i in range(80)}})["properties"]) == 30


def test_tool_names_are_sanitized_and_unique():
    taken = set()
    assert M.tool_name("e", "raro nombre/1", taken) == "raro_nombre_1"
    assert M.tool_name("e", "raro_nombre_1", taken) == "raro_nombre_1_2"
    assert M.tool_name("e", "!!!", taken) is None
    assert len(M.tool_name("e", "x" * 200, set())) <= 40


def test_render_result():
    ok = NS(content=[NS(type="text", text="hola"), NS(type="image")], isError=False, structuredContent=None)
    assert M.render_result(ok) == "hola\n[contenido image omitido]"
    assert M.render_result(NS(content=[NS(type="text", text="mal")], isError=True)).startswith("[la herramienta devolvió un error]")
    big = M.render_result(NS(content=[NS(type="text", text="x" * 50000)], isError=False))
    assert len(big) < M.MAX_OUTPUT + 100 and "recortado" in big
    assert M.render_result(NS(content=[], isError=False, structuredContent={"a": 1})) == '{"a": 1}'
    # mcp 2.x (snake_case)
    assert M.render_result(NS(content=[], is_error=False, structured_content={"a": 1})) == '{"a": 1}'
    assert M.render_result(NS(content=[NS(type="text", text="mal")], is_error=True)).startswith("[la herramienta devolvió un error]")


# ---------- integración con un servidor MCP real ----------
class Scripted(LLMProvider):
    def __init__(self, *script):
        self.script = list(script)

    def generate(self, system, messages, tools, image_png=None):
        self.last_tools = [t["name"] for t in tools]
        return self.script.pop(0)


def build(tmp_path, llm=None):
    ws = tmp_path / "ws"; ws.mkdir(parents=True, exist_ok=True)
    bus, audit = EventBus(), AuditLog(tmp_path / "a.jsonl")
    q = bus.subscribe()
    h = wire(llm or Scripted(), bus, audit, [ws], exit_fn=lambda c: None, home=tmp_path / "home", approval_timeout=5.0)
    return h, bus, audit, q


def snap(q):
    last = None
    while not q.empty():
        e = q.get_nowait()
        if e["type"] == "extensions.changed":
            last = e["payload"]
    return last


def test_add_lists_tools_and_runs_them(tmp_path):
    async def go():
        h, bus, audit, q = build(tmp_path)
        pid = tmp_path / "pid"
        await h({"type": "extensions.add", "name": "echo", "command": cmd(pid), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        names = sorted(h.extensions.exts["echo"].tools)
        assert "mcp.echo.sumar" in names and "mcp.echo.raro_nombre_1" in names and "mcp.echo.raro_nombre_1_2" in names
        t = h.extensions.tools["mcp.echo.sumar"]
        assert t.cls is C.DESTRUCTIVE and t.untrusted_output and t.description.startswith("[externa:echo] ")
        assert t.description == "[externa:echo] Suma dos enteros."          # solo la primera línea: sin la inyección de la segunda
        assert set(t.parameters["properties"]) == {"a", "b"}
        assert await t.run(a=2, b=3) == "5"
        assert (await h.extensions.tools["mcp.echo.falla"].run()).startswith("[la herramienta devolvió un error]")
        assert len(await h.extensions.tools["mcp.echo.grande"].run()) < M.MAX_OUTPUT + 100
        s = snap(q)["extensions"][0]
        assert s["state"] == "running" and {x["raw"] for x in s["tools"]} >= {"sumar", "leer_nota"}
        # baja: el proceso muere y las herramientas desaparecen
        spid = int(pid.read_text())
        await h({"type": "extensions.set_enabled", "name": "echo", "enabled": False})
        assert await wait_for(lambda: not alive(spid)) and "mcp.echo.sumar" not in h.extensions.tools
        assert audit.verify()
    asyncio.run(go())


def test_add_requires_confirmation_and_validates(tmp_path):
    async def go():
        h, bus, audit, q = build(tmp_path)
        for msg in ({"name": "echo", "command": cmd()}, {"name": "Echo!", "command": cmd(), "confirmed": True},
                    {"name": "echo", "command": cmd(), "confirmed": "true"}, {"name": "x", "command": "no-existe-xyz --a", "confirmed": True},
                    {"name": "x", "command": "", "confirmed": True}):
            await h({"type": "extensions.add", **msg})
        assert h.extensions.exts == {} and not (tmp_path / "home" / "extensions.json").exists()
        n = []
        while not q.empty():
            n.append(q.get_nowait())
        assert sum(1 for e in n if e["type"] == "ui.notice") == 5
    asyncio.run(go())


def test_mcp_tool_needs_approval_taints_and_trust_makes_it_read(tmp_path):
    async def go():
        llm = Scripted(LLMResponse(tool_calls=[ToolCall("mcp.echo.sumar", {"a": 2, "b": 3})]), LLMResponse(text="son 5"),
                       LLMResponse(tool_calls=[ToolCall("mcp.echo.sumar", {"a": 1, "b": 1})]), LLMResponse(text="son 2"))
        h, bus, audit, q = build(tmp_path, llm)
        await h({"type": "extensions.add", "name": "echo", "command": cmd(), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        # por defecto: pide aprobación humana
        await h({"type": "task", "goal": "suma"})
        assert await wait_for(lambda: any(e["type"] == "approval.requested" for e in list(q._queue)), 10)
        req = next(e for e in list(q._queue) if e["type"] == "approval.requested")["payload"]
        assert req["tool"] == "mcp.echo.sumar"
        await h({"type": "approval", "id": req["id"], "granted": True})
        await h._task
        assert "mcp.echo.sumar" in llm.last_tools
        # el usuario la marca como lectura: ya no pide aprobación
        await h({"type": "extensions.set_trust", "name": "echo", "tool": "sumar", "read": True})
        assert h.extensions.tools["mcp.echo.sumar"].cls is C.READ
        while not q.empty():
            q.get_nowait()
        await h({"type": "task", "goal": "suma otra vez"})
        await h._task
        evs = []
        while not q.empty():
            evs.append(q.get_nowait()["type"])
        assert "approval.requested" not in evs and "action.finished" in evs
        lines = [json.loads(l) for l in (tmp_path / "a.jsonl").read_text().splitlines()]
        assert any(l["event"] == "ext.trust" for l in lines)
        # persistió la confianza
        assert json.loads((tmp_path / "home" / "extensions.json").read_text())["extensions"][0]["trusted"] == ["sumar"]
        await h.extensions.stop_all()
    asyncio.run(go())


def test_taint_after_mcp_output_forces_confirmation_for_writes(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir(parents=True, exist_ok=True)
        llm = Scripted(LLMResponse(tool_calls=[ToolCall("mcp.echo.leer_nota", {})]),
                       LLMResponse(tool_calls=[ToolCall("fs.write", {"path": str(ws / "x.txt"), "content": "hola"})]),
                       LLMResponse(text="fin"))
        h, bus, audit, q = build(tmp_path, llm)
        await h({"type": "extensions.add", "name": "echo", "command": cmd(), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        await h({"type": "extensions.set_trust", "name": "echo", "tool": "leer_nota", "read": True})
        await h({"type": "task", "goal": "lee"})
        assert await wait_for(lambda: any(e["type"] == "approval.requested" for e in list(q._queue)), 10)
        req = next(e for e in list(q._queue) if e["type"] == "approval.requested")["payload"]
        assert req["tool"] == "fs.write" and req["origin"] == "observed"     # la nota externa contaminó la tarea
        await h({"type": "approval", "id": req["id"], "granted": False})
        await h._task
        assert not (ws / "x.txt").exists()
        await h.extensions.stop_all()
    asyncio.run(go())


def test_remove_and_panic_kill_the_server(tmp_path):
    async def go():
        h, bus, audit, q = build(tmp_path)
        pid = tmp_path / "pid"
        await h({"type": "extensions.add", "name": "echo", "command": cmd(pid), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        p1 = int(pid.read_text())
        await h({"type": "extensions.remove", "name": "echo"})
        assert await wait_for(lambda: not alive(p1)) and h.extensions.exts == {} and not [t for t in h.extensions.tools if t.startswith("mcp.")]
        # pánico
        await h({"type": "extensions.add", "name": "echo", "command": cmd(pid), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        p2 = int(pid.read_text())
        await h.panic()
        assert await wait_for(lambda: not alive(p2), 5)
    asyncio.run(go())


def test_server_that_crashes_reports_error_and_can_restart(tmp_path):
    async def go():
        h, bus, audit, q = build(tmp_path)
        await h({"type": "extensions.add", "name": "boom", "command": cmd(tmp_path / "pid", "crash"), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["boom"].state == "error")
        assert h.extensions.exts["boom"].error and not [t for t in h.extensions.tools if t.startswith("mcp.boom")]
        assert any(json.loads(l)["event"] == "ext.error" for l in (tmp_path / "a.jsonl").read_text().splitlines())
        assert snap(q)["extensions"][0]["state"] == "error"
    asyncio.run(go())


def test_persistence_autostart_and_disabled_tools_survive_restart(tmp_path):
    async def go():
        h, *_ = build(tmp_path)
        await h({"type": "extensions.add", "name": "echo", "command": cmd(), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        await h({"type": "extensions.set_tool", "name": "echo", "tool": "dormir", "enabled": False})
        assert "mcp.echo.dormir" in h.perms.disabled
        await h.extensions.stop_all()
        await asyncio.sleep(0.3)
        h2, bus2, audit2, q2 = build(tmp_path)
        assert h2.extensions.exts["echo"].state == "stopped"          # no arranca solo hasta start_enabled()
        h2.extensions.start_enabled()
        assert await wait_for(lambda: h2.extensions.exts["echo"].state == "running")
        s = snap(q2)["extensions"][0]
        assert {t["raw"]: t["enabled"] for t in s["tools"]}["dormir"] is False and {t["raw"]: t["enabled"] for t in s["tools"]}["sumar"] is True
        # herramienta deshabilitada: el orquestador la rechaza
        await h2.extensions.stop_all()
    asyncio.run(go())


def test_corrupt_or_hostile_extensions_file_is_ignored(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    (home / "extensions.json").write_text(json.dumps({"extensions": [
        {"name": "ok", "argv": ["echo"], "enabled": True}, {"name": "BAD NAME", "argv": ["x"]}, {"name": "x", "argv": []},
        {"name": "y", "argv": [5]}, "basura", {"name": "ok", "argv": ["dup"]}]}))
    h, *_ = build(tmp_path)
    assert list(h.extensions.exts) == ["ok"]
    (home / "extensions.json").write_text("{no json")
    h2, *_ = build(tmp_path)
    assert h2.extensions.exts == {}


def test_call_on_stopped_extension_fails_cleanly(tmp_path):
    async def go():
        h, *_ = build(tmp_path)
        await h({"type": "extensions.add", "name": "echo", "command": cmd(), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        run = h.extensions.tools["mcp.echo.sumar"].run
        await h({"type": "extensions.set_enabled", "name": "echo", "enabled": False})
        with pytest.raises(M.ExtensionError):
            await run(a=1, b=1)
    asyncio.run(go())


def test_garbage_messages(tmp_path):
    async def go():
        h, *_ = build(tmp_path)
        for m in ({"type": "extensions.nope"}, {"type": "extensions.remove", "name": "no"}, {"type": "extensions.set_enabled", "name": "no", "enabled": True},
                  {"type": "extensions.set_trust", "name": 5, "tool": [], "read": "x"}, {"type": "extensions.restart"}):
            assert await h(m) is None
    asyncio.run(go())


@pytest.mark.skipif(os.name == "nt", reason="en Windows el cierre lo hace el Job Object del watchdog (verify_windows.py)")
def test_core_shutdown_by_sigterm_leaves_no_orphan_servers(tmp_path):
    """Núcleo real como proceso: con una extensión activada, SIGTERM debe terminar también al servidor MCP."""
    import signal
    import subprocess
    home, pid = tmp_path / "home", tmp_path / "pid"
    home.mkdir()
    (home / "extensions.json").write_text(json.dumps({"extensions": [
        {"name": "echo", "argv": [sys.executable, SERVER, str(pid)], "enabled": True, "trusted": []}]}))
    env = {**os.environ, "JARVIS_HOME": str(home), "JARVIS_ROOTS": str(tmp_path / "ws"), "JARVIS_CORE_PORT": "0", "GEMINI_API_KEY": ""}
    core = subprocess.Popen([sys.executable, "-m", "core.main"], env=env, cwd=Path(__file__).parent.parent,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        assert "JARVIS_READY" in core.stdout.readline()
        end = time.time() + 20
        while time.time() < end and not pid.exists():
            time.sleep(0.1)
        assert pid.exists(), "la extensión no arrancó con el núcleo"
        spid = int(pid.read_text())
        assert alive(spid)
        core.send_signal(signal.SIGTERM)
        assert core.wait(timeout=15) == 0
        end = time.time() + 5
        while time.time() < end and alive(spid):
            time.sleep(0.1)
        assert not alive(spid)
    finally:
        if core.poll() is None:
            core.kill()


# ---------- variables de entorno por extensión ----------
def test_parse_env_validation():
    assert M.parse_env({"API_TOKEN": "abc"}) == {"API_TOKEN": "abc"} and M.parse_env(None) == {} and M.parse_env({}) == {}
    for bad in ({"1X": "a"}, {"A B": "a"}, {"A": ""}, {"A": 5}, {"A": "x" * 501}, {"A": "a\x00b"}, "A=1", [("A", "1")],
                {f"V{i}": "x" for i in range(17)}, {f"V{i}": "x" * 400 for i in range(6)}):
        with pytest.raises(M.ExtensionError):
            M.parse_env(bad)


def test_extension_env_reaches_server_but_never_disk_log_or_hud(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-gemini-que-no-debe-llegar")
    async def go():
        h, bus, audit, q = build(tmp_path)
        await h({"type": "extensions.add", "name": "echo", "command": cmd(), "confirmed": True, "env": {"MI_TOKEN": "valor-secreto-123"}})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        run = h.extensions.tools["mcp.echo.entorno"].run
        assert await run(nombre="MI_TOKEN") == "valor-secreto-123"
        assert await run(nombre="GEMINI_API_KEY") == "<no definida>"                   # la clave de Gemini no se hereda
        s = snap(q)["extensions"][0]
        assert s["env_names"] == ["MI_TOKEN"] and "valor-secreto-123" not in json.dumps(s)
        # cambiar las variables reinicia la extensión con los nuevos valores
        await h({"type": "extensions.set_env", "name": "echo", "env": {"MI_TOKEN": "otro-valor-456"}})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running" and "mcp.echo.entorno" in h.extensions.tools)
        assert await h.extensions.tools["mcp.echo.entorno"].run(nombre="MI_TOKEN") == "otro-valor-456"
        await h.extensions.stop_all()
        home = tmp_path / "home"
        for f in (home / "extensions.json", tmp_path / "a.jsonl"):
            txt = f.read_text()
            assert "valor-secreto-123" not in txt and "otro-valor-456" not in txt, f
        assert "MI_TOKEN" in (tmp_path / "a.jsonl").read_text()                         # sí queda el nombre, para auditar
        await h({"type": "extensions.remove", "name": "echo"})
        assert "ext_env_echo" not in (home / "secrets.json").read_text() if (home / "secrets.json").exists() else True
    asyncio.run(go())


def test_invalid_env_rejects_the_whole_add(tmp_path):
    async def go():
        h, bus, audit, q = build(tmp_path)
        await h({"type": "extensions.add", "name": "echo", "command": cmd(), "confirmed": True, "env": {"mal nombre": "x"}})
        assert h.extensions.exts == {} and not (tmp_path / "home" / "secrets.json").exists()
    asyncio.run(go())


# ---------- contexto no confiable por extensiones activas ----------
def test_writes_need_confirmation_while_external_tools_are_active_and_setting_can_disable_it(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir(parents=True, exist_ok=True)
        f1, f2 = ws / "uno.txt", ws / "dos.txt"
        llm = Scripted(LLMResponse(tool_calls=[ToolCall("fs.write", {"path": str(f1), "content": "a"})]), LLMResponse(text="fin"),
                       LLMResponse(tool_calls=[ToolCall("fs.write", {"path": str(f2), "content": "b"})]), LLMResponse(text="fin"))
        h, bus, audit, q = build(tmp_path, llm)
        await h({"type": "extensions.add", "name": "echo", "command": cmd(), "confirmed": True})
        assert await wait_for(lambda: h.extensions.exts["echo"].state == "running")
        await h({"type": "task", "goal": "escribe"})
        assert await wait_for(lambda: any(e["type"] == "approval.requested" for e in list(q._queue)), 10)
        req = next(e for e in list(q._queue) if e["type"] == "approval.requested")["payload"]
        assert req["tool"] == "fs.write" and req["origin"] == "observed" and req["why"] == "extensions"
        await h({"type": "approval", "id": req["id"], "granted": True})
        await h._task
        assert f1.read_text() == "a"
        # desactivando el ajuste, la escritura vuelve a ir sin confirmar
        await h({"type": "config.set", "values": {"confirm_with_extensions": False}})
        while not q.empty():
            q.get_nowait()
        await h({"type": "task", "goal": "escribe otra"})
        await h._task
        assert f2.read_text() == "b"
        await h.extensions.stop_all()
    asyncio.run(go())


def test_no_extension_means_no_extra_confirmation(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir(parents=True, exist_ok=True)
        llm = Scripted(LLMResponse(tool_calls=[ToolCall("fs.write", {"path": str(ws / "x.txt"), "content": "a"})]), LLMResponse(text="fin"))
        h, bus, audit, q = build(tmp_path, llm)
        await h({"type": "task", "goal": "escribe"})
        await h._task
        assert (ws / "x.txt").read_text() == "a"
    asyncio.run(go())
