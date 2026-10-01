import asyncio
import json

import pytest

from core import recipes as R
from core.app import wire
from core.audit import AuditLog
from core.bus import EventBus
from core.llm.provider import LLMProvider, LLMResponse, ToolCall
from tests.fakes_gui import FakeBackend
from tests.test_tools_gui import app


# ---------- funciones puras ----------
def test_steps_from_calls_and_validation():
    calls = [{"tool": "fs.write", "args": {"path": "a", "content": "x"}, "ok": True}, {"tool": "fs.read", "args": {"path": "z"}, "ok": False}, "basura",
             {"tool": "x", "args": "no-dict", "ok": True}]
    assert R.steps_from_calls(calls) == [{"tool": "fs.write", "args": {"path": "a", "content": "x"}}]
    assert R.steps_from_calls("x") == []
    for bad in ([], None, [{"tool": 1, "args": {}}], [{"tool": "a"}], [{"tool": "a", "args": {"k": "x" * 5000}}], [{"tool": "a", "args": {}}] * 41):
        with pytest.raises(R.RecipeError):
            R.validate_steps(bad)


def test_params_extract_substitute_and_validate():
    steps = [{"tool": "fs.write", "args": {"path": "/w/{{archivo}}.txt", "content": "Hola {{nombre}} y {{nombre}}", "n": 3, "l": ["{{nombre}}"]}}]
    assert R.extract_params(steps) == ["archivo", "nombre"]
    assert R.substitute(steps[0]["args"], {"archivo": "a", "nombre": "Ana"}) == {"path": "/w/a.txt", "content": "Hola Ana y Ana", "n": 3, "l": ["Ana"]}
    with pytest.raises(R.RecipeError, match="falta"):
        R.substitute(steps[0]["args"], {"archivo": "a"})
    assert R.validate_params({"a": "x", "b": "y", "extra": "z"}, ["a", "b"]) == {"a": "x", "b": "y"}
    for bad in ({"a": 5}, {}, {"a": "x" * 2001}):
        with pytest.raises(R.RecipeError):
            R.validate_params(bad, ["a"])
    assert R.substitute({"p": "{{x}}"}, {"x": "{{y}}"}) == {"p": "{{y}}"}      # un valor con llaves no se reinterpreta


def test_name_and_preconditions_validation():
    assert R.validate_name("  Informe semanal ") == "Informe semanal"
    for bad in ("", "x" * 61, "a/b", "<script>", 5):
        with pytest.raises(R.RecipeError):
            R.validate_name(bad)
    assert R.validate_preconditions([{"type": "path_exists", "path": " /a "}, {"type": "window_contains", "text": "Notas"}]) == [{"type": "path_exists", "path": "/a"}, {"type": "window_contains", "text": "Notas"}]
    for bad in ([{"type": "otra"}], [{"type": "path_exists"}], "x", [{"type": "window_contains", "text": ""}], [{"type": "path_exists", "path": "a"}] * 11):
        with pytest.raises(R.RecipeError):
            R.validate_preconditions(bad)


# ---------- integración ----------
class Script(LLMProvider):
    def __init__(self, *script):
        self.script, self.calls = list(script), 0

    def generate(self, system, messages, tools, image_png=None):
        self.calls += 1
        if not self.script:
            raise AssertionError("una receta no debe llamar al LLM")
        return self.script.pop(0)


def call(name, **a):
    return LLMResponse(tool_calls=[ToolCall(name, a)])


def build(tmp_path, llm, gui=None):
    ws = tmp_path / "ws"; ws.mkdir(exist_ok=True)
    bus, audit = EventBus(), AuditLog(tmp_path / "a.jsonl")
    q = bus.subscribe()
    h = wire(llm, bus, audit, [ws], exit_fn=lambda c: None, home=tmp_path / "home", approval_timeout=5, gui_backend=gui)
    return h, bus, audit, q, ws


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def task_and_wait(h, goal):
    await h({"type": "task", "goal": goal})
    await h._task


def test_save_recipe_from_episode_and_replay_without_llm(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir()
        f = ws / "nota.txt"
        llm = Script(call("fs.write", path=str(f), content="hola"), LLMResponse(text="hecho"))
        h, bus, audit, q, _ = build(tmp_path, llm)
        await task_and_wait(h, "crea la nota")
        assert f.read_text() == "hola" and llm.calls == 2
        ep = h.memory.episodes()[0]
        assert ep["saveable"] is True
        await h({"type": "recipes.save", "episode_id": ep["id"], "name": "Crear nota"})
        r = h.memory.recipes()[0]
        assert r["name"] == "Crear nota" and r["steps"] == [{"tool": "fs.write", "args": {"path": str(f), "content": "hola"}}] and r["tainted"] is False
        f.unlink()
        before = llm.calls
        await h({"type": "recipes.run", "id": r["id"]})
        await h._task
        assert f.read_text() == "hola" and llm.calls == before            # reproducida SIN llamadas al LLM
        r = h.memory.recipes()[0]
        assert r["runs"] == 1 and r["ok_runs"] == 1 and r["last_error"] == ""
        notices = [e["payload"]["text"] for e in drain(q) if e["type"] == "ui.notice"]
        assert any("sin usar el modelo" in n for n in notices)
        lines = [json.loads(l)["event"] for l in (tmp_path / "a.jsonl").read_text().splitlines()]
        assert "recipe.saved" in lines and "recipe.started" in lines and "recipe.finished" in lines
    asyncio.run(go())


def test_parameters_defaults_and_overrides(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir()
        llm = Script(call("fs.write", path=str(ws / "a.txt"), content="Hola Ana"), LLMResponse(text="ok"))
        h, bus, audit, q, _ = build(tmp_path, llm)
        await task_and_wait(h, "x")
        await h({"type": "recipes.save", "episode_id": h.memory.episodes()[0]["id"], "name": "saludo"})
        rid = h.memory.recipes()[0]["id"]
        await h({"type": "recipes.param", "id": rid, "step": 0, "arg": "content", "name": "mensaje"})
        await h({"type": "recipes.param", "id": rid, "step": 0, "arg": "path", "name": "ruta"})
        r = h.memory.recipe(rid)
        assert r["steps"][0]["args"] == {"path": "{{ruta}}", "content": "{{mensaje}}"} and r["params"] == {"mensaje": "Hola Ana", "ruta": str(ws / "a.txt")}
        await h({"type": "recipes.run", "id": rid, "params": {"mensaje": "Adiós Luis"}})      # ruta usa el valor por defecto
        await h._task
        assert (ws / "a.txt").read_text(encoding="utf-8") == "Adiós Luis"
        # parámetros inválidos / argumentos que no son texto / pasos inexistentes
        drain(q)
        for m in ({"step": 9, "arg": "content", "name": "x"}, {"step": 0, "arg": "nope", "name": "x"}, {"step": 0, "arg": "content", "name": "Mal Nombre"}):
            await h({"type": "recipes.param", "id": rid, **m})
        assert sum(1 for e in drain(q) if e["type"] == "ui.notice" and e["payload"]["level"] == "error") == 3
    asyncio.run(go())


def test_replay_goes_through_policy_and_approvals_and_stops_on_failure(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir()
        (ws / "borrame.txt").write_text("x")
        llm = Script(call("fs.delete", path=str(ws / "borrame.txt")), LLMResponse(text="borrado"))
        h, bus, audit, q, _ = build(tmp_path, llm)
        await h({"type": "task", "goal": "borra"})
        for _ in range(100):
            await asyncio.sleep(0.05)
            req = next((e for e in list(q._queue) if e["type"] == "approval.requested"), None)
            if req:
                break
        await h({"type": "approval", "id": req["payload"]["id"], "granted": True})
        await h._task
        await h({"type": "recipes.save", "episode_id": h.memory.episodes()[0]["id"], "name": "borrar"})
        rid = h.memory.recipes()[0]["id"]
        (ws / "borrame.txt").write_text("otra vez")
        drain(q)
        # la receta NO concede permisos: el borrado vuelve a pedir confirmación
        await h({"type": "recipes.run", "id": rid})
        for _ in range(100):
            await asyncio.sleep(0.05)
            req = next((e for e in list(q._queue) if e["type"] == "approval.requested"), None)
            if req:
                break
        assert req["payload"]["tool"] == "fs.delete"
        assert (ws / "borrame.txt").exists()
        await h({"type": "approval", "id": req["payload"]["id"], "granted": False})        # denegar detiene la receta
        await h._task
        r = h.memory.recipe(rid)
        assert (ws / "borrame.txt").exists() and r["runs"] == 1 and r["ok_runs"] == 0 and "denegada" in r["last_error"]
        assert llm.calls == 2                                                                  # ninguna llamada nueva
    asyncio.run(go())


def test_preconditions_block_execution_and_no_steps_run(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir()
        llm = Script(call("fs.write", path=str(ws / "out.txt"), content="x"), LLMResponse(text="ok"))
        h, bus, audit, q, _ = build(tmp_path, llm)
        await task_and_wait(h, "x")
        (ws / "out.txt").unlink()
        await h({"type": "recipes.save", "episode_id": h.memory.episodes()[0]["id"], "name": "r"})
        rid = h.memory.recipes()[0]["id"]
        await h({"type": "recipes.set_preconditions", "id": rid, "items": [{"type": "path_exists", "path": str(ws / "entrada.csv")}]})
        drain(q)
        await h({"type": "recipes.run", "id": rid})
        await h._task
        assert not (ws / "out.txt").exists()                                                  # no se ejecutó ningún paso
        notices = [e["payload"]["text"] for e in drain(q) if e["type"] == "ui.notice"]
        assert any("precondición no cumplida" in n and "explore" in n for n in notices)
        (ws / "entrada.csv").write_text("a")
        await h({"type": "recipes.run", "id": rid})
        await h._task
        assert (ws / "out.txt").exists()
        # fuera de las carpetas permitidas
        await h({"type": "recipes.set_preconditions", "id": rid, "items": [{"type": "path_exists", "path": "/etc/hostname"}]})
        (ws / "out.txt").unlink()
        await h({"type": "recipes.run", "id": rid}); await h._task
        assert not (ws / "out.txt").exists()
        # tipos inválidos
        drain(q)
        await h({"type": "recipes.set_preconditions", "id": rid, "items": [{"type": "x"}]})
        assert any(e["type"] == "ui.notice" and e["payload"]["level"] == "error" for e in drain(q))
    asyncio.run(go())


def test_disabled_tool_blocks_recipe(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir()
        llm = Script(call("fs.write", path=str(ws / "o.txt"), content="x"), LLMResponse(text="ok"))
        h, bus, audit, q, _ = build(tmp_path, llm)
        await task_and_wait(h, "x")
        (ws / "o.txt").unlink()
        await h({"type": "recipes.save", "episode_id": h.memory.episodes()[0]["id"], "name": "r"})
        await h({"type": "permissions.set_tool", "tool": "fs.write", "enabled": False})
        await h({"type": "recipes.run", "id": h.memory.recipes()[0]["id"]}); await h._task
        assert not (ws / "o.txt").exists() and "deshabilitada" in h.memory.recipes()[0]["last_error"]
    asyncio.run(go())


def test_tainted_episode_is_flagged_and_replay_keeps_taint_rules(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir()
        (ws / "in.txt").write_text("datos")
        llm = Script(call("fs.read", path=str(ws / "in.txt")), call("fs.write", path=str(ws / "out.txt"), content="x"), LLMResponse(text="ok"))
        h, bus, audit, q, _ = build(tmp_path, llm)
        await h({"type": "task", "goal": "copia"})
        for _ in range(100):
            await asyncio.sleep(0.05)
            req = next((e for e in list(q._queue) if e["type"] == "approval.requested"), None)
            if req:
                break
        await h({"type": "approval", "id": req["payload"]["id"], "granted": True}); await h._task
        drain(q)
        await h({"type": "recipes.save", "episode_id": h.memory.episodes()[0]["id"], "name": "copiar"})
        r = h.memory.recipes()[0]
        assert r["tainted"] is True and [s["tool"] for s in r["steps"]] == ["fs.read", "fs.write"]
        assert any("contenido no confiable" in e["payload"]["text"] for e in drain(q) if e["type"] == "ui.notice")
        (ws / "out.txt").unlink()
        await h({"type": "recipes.run", "id": r["id"]})
        for _ in range(100):
            await asyncio.sleep(0.05)
            req = next((e for e in list(q._queue) if e["type"] == "approval.requested"), None)
            if req:
                break
        assert req["payload"]["tool"] == "fs.write" and req["payload"]["origin"] == "observed"    # tras leer, escribir vuelve a pedir confirmación
        await h({"type": "approval", "id": req["payload"]["id"], "granted": True}); await h._task
        assert (ws / "out.txt").exists()
    asyncio.run(go())


def test_only_successful_saveable_episodes_and_validation(tmp_path):
    async def go():
        h, bus, audit, q, _ = build(tmp_path, Script(LLMResponse(text="solo texto"), LLMResponse(text="otra")))
        await task_and_wait(h, "charla")
        assert h.memory.episodes()[0]["saveable"] is False                                       # sin llamadas: nada que guardar
        drain(q)
        for m in ({"episode_id": h.memory.episodes()[0]["id"], "name": "x"}, {"episode_id": 999, "name": "x"}, {"episode_id": "1", "name": "x"}):
            await h({"type": "recipes.save", **m})
        assert sum(1 for e in drain(q) if e["type"] == "ui.notice" and e["payload"]["level"] == "error") == 3
        assert h.memory.recipes() == []
        for m in ({"type": "recipes.run", "id": 99}, {"type": "recipes.delete", "id": "x"}, {"type": "recipes.nope"}, {"type": "recipes.param"}):
            await h(m)
    asyncio.run(go())


def test_duplicate_names_delete_and_limit(tmp_path):
    async def go():
        ws = tmp_path / "ws"; ws.mkdir()
        llm = Script(call("fs.write", path=str(ws / "a"), content="x"), LLMResponse(text="ok"))
        h, bus, audit, q, _ = build(tmp_path, llm)
        await task_and_wait(h, "x")
        eid = h.memory.episodes()[0]["id"]
        await h({"type": "recipes.save", "episode_id": eid, "name": "uno"})
        drain(q)
        await h({"type": "recipes.save", "episode_id": eid, "name": "uno"})
        assert any("ya existe" in e["payload"]["text"] for e in drain(q) if e["type"] == "ui.notice")
        await h({"type": "recipes.delete", "id": h.memory.recipes()[0]["id"]})
        assert h.memory.recipes() == []
    asyncio.run(go())


def test_gui_recipe_replays_by_name_not_by_number(tmp_path):
    async def go():
        be = app()
        llm = Script(call("gui.observe", window="Banco"), call("gui.type", id=2, text="Ana"), call("gui.click", id=4), LLMResponse(text="listo"))
        h, bus, audit, q, _ = build(tmp_path, llm, gui=be)
        await h({"type": "task", "goal": "saluda a Ana"})
        for _ in range(200):
            await asyncio.sleep(0.05)
            req = next((e for e in list(q._queue) if e["type"] == "approval.requested"), None)
            if req:
                await h({"type": "approval", "id": req["payload"]["id"], "granted": True})
                drain(q)
            if h._task.done():
                break
        await h._task
        eps = h.memory.episodes()
        await h({"type": "recipes.save", "episode_id": eps[0]["id"], "name": "saludar"})
        r = h.memory.recipes()[0]
        assert [s["tool"] for s in r["steps"]] == ["gui.observe", "gui.type", "gui.click"]
        assert r["steps"][1]["args"] == {"name": "Nombre", "role": "edit", "text": "Ana"} and r["steps"][2]["args"] == {"name": "Saludar", "role": "button"}
        # el estado vuelve a «inicial» y la receta se repite aunque los números hayan cambiado
        next(e for e in be.wins[10]["els"] if e.role == "text").name = "Estado: inicial"
        be.wins[10]["els"].insert(0, be.wins[10]["els"].pop())                  # se reordena la interfaz: los ids ya no coinciden
        await h({"type": "recipes.param", "id": r["id"], "step": 1, "arg": "text", "name": "quien"})
        await h({"type": "recipes.run", "id": r["id"], "params": {"quien": "Luis"}})
        for _ in range(200):
            await asyncio.sleep(0.05)
            req = next((e for e in list(q._queue) if e["type"] == "approval.requested"), None)
            if req:
                await h({"type": "approval", "id": req["payload"]["id"], "granted": True})
                drain(q)
            if h._task.done():
                break
        await h._task
        assert any(e.name == "Estado: Hola, Luis" for e in be.wins[10]["els"])
        assert h.memory.recipes()[0]["ok_runs"] == 1
    asyncio.run(go())
