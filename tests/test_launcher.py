import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("launch", Path(__file__).parent.parent / "tools" / "launch.py")
L = importlib.util.module_from_spec(spec)
sys.modules["launch"] = L
spec.loader.exec_module(L)

posix = pytest.mark.skipif(os.name == "nt", reason="el fake usa señales POSIX")

FAKE_CORE = """
import os, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(f"{os.getpid()} {child.pid}")
print("ruido previo", flush=True)
print("JARVIS_READY port=4321 token=tok-secreto_123", flush=True)
for i in range(2000):
    print("log", i, flush=True)   # más que el buffer de una tubería: si no se drena, se bloquea
time.sleep(60)
"""

FAKE_HUD = """
import json, os, sys
json.dump({"argv": sys.argv[1:], "port": os.environ.get("JARVIS_PORT"), "token": os.environ.get("JARVIS_TOKEN"),
           "gemini": os.environ.get("GEMINI_API_KEY")}, open(sys.argv[1], "w"))
"""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # un zombi no cuenta como vivo
        return "Z" not in Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return True


def wait_dead(pid: int, t: float = 5.0) -> bool:
    end = time.time() + t
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_core_command_picks_watchdog():
    assert L.core_command(True)[-1] == "watchdog.watchdog"
    assert L.core_command(False)[-1] == "core.main"


def test_ready_regex_requires_whole_line():
    assert L.READY.match("JARVIS_READY port=8765 token=abc-_9\n").groups() == ("8765", "abc-_9")
    assert not L.READY.match("x JARVIS_READY port=1 token=a")
    assert not L.READY.match("JARVIS_READY port=x token=a")


def test_hud_env_strips_api_key_and_sets_connection(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    env = L.hud_env(1, "t")
    assert "GEMINI_API_KEY" not in env and env["JARVIS_PORT"] == "1" and env["JARVIS_TOKEN"] == "t"


def test_find_hud_priority(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_HUD_BIN", raising=False)
    monkeypatch.setattr(L, "REPO", tmp_path)
    assert L.find_hud(None) is None
    built = tmp_path / "hud" / "src-tauri" / "target" / "release" / L.HUD_NAME
    built.parent.mkdir(parents=True)
    built.write_text("")
    assert L.find_hud(None) == [str(built)]
    monkeypatch.setenv("JARVIS_HUD_BIN", "/env/hud")
    assert L.find_hud(None) == ["/env/hud"]
    assert L.find_hud("/arg/hud") == ["/arg/hud"]


def test_start_core_fails_if_core_dies():
    with pytest.raises(L.LaunchError, match="terminó antes"):
        L.start_core([sys.executable, "-c", "print('boom')"], timeout=10)


@posix
def test_start_core_times_out_and_kills(tmp_path):
    marker = tmp_path / "pids"
    code = f"import os,time; open({str(marker)!r},'w').write(str(os.getpid())); time.sleep(60)"
    with pytest.raises(L.LaunchError, match="JARVIS_READY"):
        L.start_core([sys.executable, "-c", code], timeout=1.0)
    assert wait_dead(int(marker.read_text()))


@posix
def test_run_passes_connection_by_env_not_argv_and_cleans_up(tmp_path, monkeypatch, capfd):
    pids, out = tmp_path / "pids", tmp_path / "hud.json"
    hud = tmp_path / "hud.py"
    hud.write_text(FAKE_HUD)
    monkeypatch.setattr(L, "core_command", lambda w: [sys.executable, "-c", FAKE_CORE, str(pids)])
    monkeypatch.setenv("GEMINI_API_KEY", "no-debe-llegar")
    wrapper = tmp_path / "wrap"
    wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {hud} {out}\n")
    wrapper.chmod(0o755)
    rc = L.run(["--timeout", "20", "--hud", str(wrapper)])
    got = json.loads(out.read_text())
    assert rc == 0
    assert got == {"argv": [str(out)], "port": "4321", "token": "tok-secreto_123", "gemini": None}
    core_pid, child_pid = map(int, pids.read_text().split())
    assert wait_dead(core_pid) and wait_dead(child_pid)   # el núcleo y sus hijos mueren al cerrar el HUD
    err = capfd.readouterr().err
    assert "tok-secreto_123" not in err                  # el token no se filtra a los logs


@posix
def test_run_without_hud_binary_is_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("JARVIS_HUD_BIN", raising=False)
    monkeypatch.setattr(L, "REPO", tmp_path)
    assert L.run([]) == 2
    assert "No hay HUD compilado" in capsys.readouterr().err


@posix
def test_run_missing_hud_executable_stops_core(tmp_path, monkeypatch):
    pids = tmp_path / "pids"
    monkeypatch.setattr(L, "core_command", lambda w: [sys.executable, "-c", FAKE_CORE, str(pids)])
    assert L.run(["--timeout", "20", "--hud", str(tmp_path / "no-existe")]) == 1
    core_pid, child_pid = map(int, pids.read_text().split())
    assert wait_dead(core_pid) and wait_dead(child_pid)
