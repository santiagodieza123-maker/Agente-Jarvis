import json

import pytest

from core.orchestrator import Tool
from core.permissions import PermissionError_, PermissionStore
from core.policy import Action, ActionClass as C, Decision as D, Origin as O, Policy
from core.tools_fs import FsTools


def build(tmp_path, roots=None):
    ws = tmp_path / "ws"; ws.mkdir(exist_ok=True)
    fs = FsTools([ws])
    tools = {t.name: t for t in fs.tools()}
    policy = Policy(allowed_roots=[str(ws)])
    store = PermissionStore(tmp_path / "home" / "permissions.json", policy, fs, roots or [ws], tools, protected=[tmp_path / "home", tmp_path / "repo"])
    return store, policy, fs, ws


def test_locked_classes_cannot_be_relaxed(tmp_path):
    store, policy, *_ = build(tmp_path)
    for cls in ("destructive", "elevated"):
        with pytest.raises(PermissionError_):
            store.set_confirm(cls, False)
    assert [c["locked"] for c in store.snapshot()["classes"] if c["name"] in ("destructive", "elevated")] == [True, True]


def test_policy_ignores_confirm_false_for_locked_classes(tmp_path):
    """Defensa en profundidad: aunque alguien manipule el dict, DESTRUCTIVE sigue pidiendo confirmación."""
    _, policy, *_ = build(tmp_path)
    policy.confirm[C.DESTRUCTIVE] = False
    assert policy.evaluate(Action("fs.delete", C.DESTRUCTIVE, O.USER)) is D.CONFIRM


def test_relaxing_write_changes_policy_and_persists(tmp_path):
    store, policy, *_ = build(tmp_path)
    store.set_confirm("write_reversible", True)
    assert policy.evaluate(Action("fs.write", C.WRITE_REVERSIBLE, O.USER)) is D.CONFIRM
    store2, policy2, *_ = build(tmp_path)               # reabrir: lo guardado se reaplica
    assert policy2.evaluate(Action("fs.write", C.WRITE_REVERSIBLE, O.USER)) is D.CONFIRM


@pytest.mark.parametrize("cls,val", [("nope", True), ("read", "si"), ("read", None), (None, True)])
def test_invalid_confirm_input(tmp_path, cls, val):
    with pytest.raises(PermissionError_):
        build(tmp_path)[0].set_confirm(cls, val)


def test_tool_toggle_persists_and_validates(tmp_path):
    store, *_ = build(tmp_path)
    store.set_tool("fs.delete", False)
    assert "fs.delete" in build(tmp_path)[0].disabled
    with pytest.raises(PermissionError_):
        store.set_tool("shell.exec", False)               # no existe en este catálogo
    with pytest.raises(PermissionError_):
        store.set_tool("fs.read", "no")


def test_add_root_updates_policy_and_fs_tools(tmp_path):
    store, policy, fs, ws = build(tmp_path)
    extra = tmp_path / "otra" / "carpeta"; extra.mkdir(parents=True)
    store.add_root(str(extra))
    assert str(extra.resolve()) in policy.allowed_roots and extra.resolve() in fs.roots
    (extra / "a.txt").write_text("hola")
    assert fs.read(str(extra / "a.txt")) == "hola"        # la herramienta ya puede leer ahí
    store.remove_root(str(extra))
    with pytest.raises(PermissionError):
        fs.read(str(extra / "a.txt"))


@pytest.mark.parametrize("bad", ["/", "/etc", "/usr/lib", "relativa/ruta", "", None, 5, "/no/existe/seguro", "x" * 600])
def test_dangerous_or_invalid_roots_rejected(tmp_path, bad):
    with pytest.raises(PermissionError_):
        build(tmp_path)[0].add_root(bad)


def test_home_and_protected_dirs_rejected(tmp_path):
    from pathlib import Path
    store, *_ = build(tmp_path)
    (tmp_path / "home").mkdir(exist_ok=True); (tmp_path / "repo" / "sub").mkdir(parents=True)
    for bad in (Path.home(), tmp_path / "home", tmp_path / "repo", tmp_path / "repo" / "sub", tmp_path):
        with pytest.raises(PermissionError_):
            store.add_root(str(bad))                      # tmp_path contiene repo/home: también se rechaza


def test_corrupt_or_malicious_config_file_is_survivable(tmp_path):
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "permissions.json").write_text(json.dumps(
        {"roots": ["/", "/etc", 5], "confirm": {"destructive": False, "read": "x", "zzz": True}, "disabled": ["fs.read", "nada"]}))
    store, policy, *_ = build(tmp_path)
    assert store.roots == [] and policy.confirm[C.DESTRUCTIVE] is True and policy.confirm[C.READ] is False
    assert store.disabled == {"fs.read"}
    (tmp_path / "home" / "permissions.json").write_text("{no es json")
    build(tmp_path)                                       # no revienta


def test_snapshot_shape(tmp_path):
    snap = build(tmp_path)[0].snapshot()
    assert {c["name"] for c in snap["classes"]} == {"read", "write_reversible", "destructive", "elevated"}
    assert all({"name", "cls", "enabled"} <= t.keys() for t in snap["tools"]) and len(snap["roots"]) == 1


def test_disabled_tool_is_hidden_from_llm_and_rejected(tmp_path):
    import asyncio

    from core.audit import AuditLog
    from core.bus import EventBus
    from core.llm.provider import LLMProvider, LLMResponse, ToolCall
    from core.orchestrator import Orchestrator

    class L(LLMProvider):
        def __init__(self): self.offered, self.sys, self.n = [], "", 0
        def generate(self, system, messages, tools, image_png=None):
            self.offered.append({t["name"] for t in tools}); self.sys = system; self.n += 1
            return LLMResponse(tool_calls=[ToolCall("fs.read", {"path": "/x"})]) if self.n == 1 else LLMResponse(text="ok")

    ran = []
    t = Tool("fs.read", C.READ, lambda path: ran.append(path), "r"), Tool("fs.list", C.READ, lambda path: "", "l")
    async def ap(a, b, c): return True
    l = L()
    o = Orchestrator(l, {x.name: x for x in t}, Policy(), AuditLog(tmp_path / "a.jsonl"), EventBus(), ap,
                     is_enabled=lambda n: n != "fs.read", memory_block=lambda: "\n\nNOTAS: usa español")
    asyncio.run(o.run("x"))
    assert l.offered[0] == {"fs.list"} and ran == []     # no se ofrece y, si lo pide igualmente, se rechaza
    assert "NOTAS: usa español" in l.sys
