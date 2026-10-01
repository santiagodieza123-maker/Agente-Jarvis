import asyncio
import os
import sys

import pytest

from core.policy import ActionClass
from core.tools_shell import ShellTools, clean_env

posix = pytest.mark.skipif(os.name == "nt", reason="comandos de prueba POSIX")


def run(c):
    return asyncio.run(c)


def test_clean_env_strips_secrets():
    e = clean_env({"PATH": "/bin", "GEMINI_API_KEY": "x", "GITHUB_TOKEN": "y", "DB_PASSWORD": "z", "HOME": "/h"})
    assert set(e) == {"PATH", "HOME"}


def test_tool_is_always_confirm_class_and_untrusted(tmp_path):
    t = ShellTools(tmp_path).tools()[0]
    assert t.cls is ActionClass.DESTRUCTIVE and t.untrusted_output


@posix
def test_runs_in_cwd_and_reports_exit(tmp_path):
    out = run(ShellTools(tmp_path).exec("pwd; echo hola; exit 3"))
    assert str(tmp_path) in out and "hola" in out and out.startswith("[exit 3]")


@posix
def test_child_does_not_inherit_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "SUPER-SECRETO")
    assert "SUPER-SECRETO" not in run(ShellTools(tmp_path).exec("env"))


@posix
def test_timeout_kills_whole_tree(tmp_path):
    marker = tmp_path / "vivo"
    cmd = f"(sleep 1.5; touch {marker}) & sleep 30"
    out = run(ShellTools(tmp_path, timeout=0.5).exec(cmd))
    assert "timeout" in out
    import time; time.sleep(2)
    assert not marker.exists()          # el nieto también murió


@posix
def test_output_cap_kills_runaway(tmp_path):
    out = run(ShellTools(tmp_path, max_output=1000, timeout=10).exec("yes"))
    assert "truncada" in out and len(out) < 1300
