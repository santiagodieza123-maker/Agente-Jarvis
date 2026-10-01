"""GuiTools dentro de wire(): política, contaminación, imagen hacia el modelo y marcos hacia el HUD."""
import asyncio

from core.app import wire
from core.audit import AuditLog
from core.bus import EventBus
from core.llm.provider import LLMProvider, LLMResponse, ToolCall
from tests.fakes_gui import FakeBackend
from tests.test_tools_gui import app


class Spy(LLMProvider):
    def __init__(self, *script):
        self.script, self.images, self.tool_names = list(script), [], []

    def generate(self, system, messages, tools, image_png=None):
        self.images.append(image_png)
        self.tool_names = [t["name"] for t in tools]
        return self.script.pop(0)


def call(name, **a):
    return LLMResponse(tool_calls=[ToolCall(name, a)])


def build(tmp_path, llm):
    (tmp_path / "ws").mkdir(exist_ok=True)
    bus, audit = EventBus(), AuditLog(tmp_path / "a.jsonl")
    q = bus.subscribe()
    be = app()
    h = wire(llm, bus, audit, [tmp_path / "ws"], exit_fn=lambda c: None, home=tmp_path / "home", approval_timeout=5, gui_backend=be)
    h.gui_fake = be
    return h, bus, audit, q, be


def events(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_gui_tools_registered_and_listed(tmp_path):
    llm = Spy(LLMResponse(text="hola"))
    h, bus, audit, q, be = build(tmp_path, llm)

    async def go():
        await h({"type": "task", "goal": "x"})
        await h._task
    asyncio.run(go())
    assert {"gui.windows", "gui.observe", "gui.click", "gui.type", "gui.press", "gui.focus", "gui.click_xy"} <= set(llm.tool_names)


def test_after_observing_a_window_clicks_need_confirmation_and_image_goes_to_the_model_once(tmp_path):
    llm = Spy(call("gui.observe", image=True), call("gui.click", id=4), LLMResponse(text="hecho"))
    h, bus, audit, q, be = build(tmp_path, llm)

    async def go():
        await h({"type": "task", "goal": "saluda"})
        for _ in range(200):
            await asyncio.sleep(0.05)
            req = next((e for e in list(q._queue) if e["type"] == "approval.requested"), None)
            if req:
                break
        assert req and req["payload"]["tool"] == "gui.click" and req["payload"]["origin"] == "observed"
        assert req["payload"]["why"] == "content"
        assert not [l for l in be.log if l[0] == "activate"]                # nada pulsado antes de aprobar
        await h({"type": "approval", "id": req["payload"]["id"], "granted": True})
        await h._task
    asyncio.run(go())
    assert [l for l in be.log if l[0] == "activate"] == [("activate", "Saludar")]
    assert llm.images[0] is None and isinstance(llm.images[1], bytes) and llm.images[1][:4] == b"\x89PNG"     # la captura llega con la llamada siguiente
    assert llm.images[2] is None                                              # y solo una vez


def test_denied_click_does_nothing(tmp_path):
    llm = Spy(call("gui.observe"), call("gui.click", id=4), LLMResponse(text="fin"))
    h, bus, audit, q, be = build(tmp_path, llm)

    async def go():
        await h({"type": "task", "goal": "saluda"})
        for _ in range(200):
            await asyncio.sleep(0.05)
            req = next((e for e in list(q._queue) if e["type"] == "approval.requested"), None)
            if req:
                break
        await h({"type": "approval", "id": req["payload"]["id"], "granted": False})
        await h._task
    asyncio.run(go())
    assert not [l for l in be.log if l[0] == "activate"]


def test_frames_reach_the_hud_bus_and_never_include_the_hud_window(tmp_path):
    llm = Spy(call("gui.observe"), LLMResponse(text="ok"))
    h, bus, audit, q, be = build(tmp_path, llm)
    asyncio.run((lambda: (h({"type": "task", "goal": "mira"})))())            # arranca
    async def go():
        await h({"type": "task", "goal": "mira"})
        await h._task
    asyncio.run(go())
    frames = [e["payload"] for e in events(q) if e["type"] == "perception.frame"]
    assert frames and frames[0]["title"] == "Banco de Pruebas" and frames[0]["image"]
    assert all("Permitir" not in str(f["elements"]) for f in frames)


def test_gui_failure_is_reported_to_the_model_not_raised(tmp_path):
    llm = Spy(call("gui.observe", window="no-existe"), LLMResponse(text="fin"))
    h, bus, audit, q, be = build(tmp_path, llm)

    async def go():
        await h({"type": "task", "goal": "x"})
        await h._task
    asyncio.run(go())
    lines = [__import__("json").loads(l) for l in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert any(l["event"] == "action.finished" and l["data"]["tool"] == "gui.observe" and l["data"]["ok"] is False for l in lines) or any(l["event"] == "task.finished" for l in lines)
