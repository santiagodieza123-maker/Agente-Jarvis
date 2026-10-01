import asyncio
import json
from pathlib import Path

import pytest

from core.app import wire
from core.audit import AuditLog
from core.bus import EventBus
from core.llm.provider import LLMProvider, LLMResponse, ToolCall
from core.sensitive import sensitive_hits


@pytest.mark.parametrize("cmd, expect", [
    ("cat ~/.jarvis/secrets.json", True), ("type C:\\Users\\yo\\.jarvis\\secrets.json", True), ("cat .env", True),
    ("Get-Content C:\\proyecto\\.env ", True), ("cat ~/.ssh/id_rsa", True), ("cmdkey /list", True), ("type %USERPROFILE%\\.aws\\credentials", True),
    ("echo $GEMINI_API_KEY", True), ("python -c \"import keyring\"", True), ("cat /home/u/.jarvis/audit.jsonl", True),
    ("ls -la", False), ("echo hola > nota.txt", False), ("git status", False), ("cat environment.txt", False), ("dir C:\\Users\\yo\\Documents", False),
])
def test_command_heuristics(cmd, expect):
    assert bool(sensitive_hits("shell.exec", {"command": cmd})) is expect, cmd


def test_extra_paths_and_dedup():
    h = sensitive_hits("fs.read", {"path": "/home/u/mi-casa-jarvis/x"}, [Path("/home/u/mi-casa-jarvis")])
    assert h == ["la carpeta de configuración y secretos de Jarvis"]
    assert len(sensitive_hits("shell.exec", {"command": "cat ~/.jarvis/secrets.json ~/.jarvis/audit.jsonl"})) == len(set(sensitive_hits("shell.exec", {"command": "cat ~/.jarvis/secrets.json ~/.jarvis/audit.jsonl"})))


def test_approval_payload_carries_warnings(tmp_path):
    class L(LLMProvider):
        def __init__(self): self.n = 0
        def generate(self, system, messages, tools, image_png=None):
            self.n += 1
            return LLMResponse(tool_calls=[ToolCall("shell.exec", {"command": "cat ~/.jarvis/secrets.json"})]) if self.n == 1 else LLMResponse(text="fin")

    async def go():
        ws = tmp_path / "ws"; ws.mkdir()
        bus, audit = EventBus(), AuditLog(tmp_path / "a.jsonl")
        q = bus.subscribe()
        h = wire(L(), bus, audit, [ws], exit_fn=lambda c: None, home=tmp_path / "home", approval_timeout=5)
        await h({"type": "task", "goal": "x"})
        for _ in range(100):
            await asyncio.sleep(0.05)
            evs = list(q._queue)
            req = next((e for e in evs if e["type"] == "approval.requested"), None)
            if req:
                break
        assert req and req["payload"]["tool"] == "shell.exec" and req["payload"]["warnings"]
        await h({"type": "approval", "id": req["payload"]["id"], "granted": False})
        await h._task
    asyncio.run(go())
