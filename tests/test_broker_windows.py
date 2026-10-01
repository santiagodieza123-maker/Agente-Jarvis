"""Broker real sobre una tubería con nombre (solo Windows): ACL, autenticación, operaciones cerradas, primer ejemplar y parada."""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="tuberías con nombre y ACL de Windows")


@pytest.fixture()
def live(tmp_path):
    from broker import pipe_win as pw
    pipe = rf"\\.\pipe\jarvis-test-{os.getpid()}-{int(time.time() * 1000) % 100000}"
    home, ddir = tmp_path / "home", tmp_path / "bdata"
    home.mkdir()
    cmd = [sys.executable, "-m", "broker.service", "--home", str(home), "--pipe", pipe, "--dir", str(ddir), "--insecure-auto-approve", "--dry-run"]
    proc = subprocess.Popen(cmd, cwd=Path(__file__).parent.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    line = proc.stdout.readline() + proc.stdout.readline()
    assert "BROKER_READY" in line, line
    from core.broker_client import BrokerClient
    yield proc, pipe, BrokerClient(home, pipe=pipe), home, ddir, pw
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def test_ping_and_closed_operations(live):
    proc, pipe, cl, home, ddir, pw = live
    st = cl.status()
    assert st["running"] and st["elevated"] == pw.is_admin() and st["dry_run"] is True and st["services"] == []
    r = cl.call("winget_install", {"id": "Microsoft.PowerToys"})
    assert r["dry_run"] and r["argv"][:3] == ["winget", "install", "--id"] and "Microsoft.PowerToys" in r["argv"]
    from core.broker_client import BrokerError
    with pytest.raises(BrokerError, match="lista permitida"):
        cl.call("service_control", {"name": "Spooler", "action": "status"})
    cl.call("allow_service", {"name": "Spooler"})
    assert cl.call("service_control", {"name": "Spooler", "action": "status"})["argv"][-1] == "(Get-Service -Name 'Spooler').Status"
    assert (ddir / "allowed_services.json").exists() and (ddir / "broker.log").exists()
    for bad in ({"id": "x; calc"}, {"id": "a b"}, {}):
        with pytest.raises(BrokerError):
            cl.call("winget_install", bad)
    with pytest.raises(BrokerError, match="no permitida"):
        cl.call("powershell", {"command": "calc"})


def test_pipe_acl_only_user_and_system(live):
    proc, pipe, cl, home, ddir, pw = live
    sddl = pw.acl_of(pipe)
    print("SDDL de la tubería:", sddl)
    sid = pw.user_sid()
    assert (sid in sddl or (sid.endswith("-500") and ";;;LA)" in sddl)) and ";;;SY)" in sddl     # SDDL abrevia el RID 500 como "LA"
    assert sddl.count("(A;") == 2
    for everyone in (";;;WD)", ";;;AU)", ";;;BU)", ";;;AN)", ";;;NU)"):
        assert everyone not in sddl, sddl


def test_wrong_key_unsigned_and_replayed_messages_are_rejected(live):
    proc, pipe, cl, home, ddir, pw = live
    from broker.protocol import make_request
    bad = pw.call(pipe, make_request(b"z" * 32, "ping"))
    assert bad["ok"] is False and "firma" in bad["error"]
    req = make_request(cl._key(), "ping")
    assert pw.call(pipe, req)["ok"] is True
    assert "repetido" in pw.call(pipe, req)["error"]                             # el mismo mensaje no se acepta dos veces
    assert pw.call(pipe, {"op": "ping"})["ok"] is False
    assert cl.status()["running"]                                                # y el broker sigue vivo tras todo eso


def test_second_instance_cannot_take_over_the_pipe(live):
    proc, pipe, cl, home, ddir, pw = live
    other = subprocess.run([sys.executable, "-m", "broker.service", "--home", str(home), "--pipe", pipe, "--dir", str(ddir), "--insecure-auto-approve", "--dry-run"],
                           cwd=Path(__file__).parent.parent, capture_output=True, text=True, timeout=60)
    assert other.returncode != 0                                                 # FILE_FLAG_FIRST_PIPE_INSTANCE: no se puede suplantar
    assert cl.status()["running"]


def test_shutdown_stops_the_process(live):
    proc, pipe, cl, home, ddir, pw = live
    cl.call("shutdown")
    assert proc.wait(timeout=20) == 0
    assert cl.status()["running"] is False


def test_confirmation_dialog_uses_default_no_and_shows_the_command(monkeypatch):
    from broker import pipe_win as pw
    seen = {}

    def fake(hwnd, text, title, flags):
        seen.update(text=text, title=title, flags=flags)
        return 7                                                                 # IDNO
    monkeypatch.setattr(pw.u32, "MessageBoxW", fake, raising=False)
    from broker.ops import describe
    assert pw.confirm_dialog("winget_install", describe("winget_install", {"id": "A.B"})) is False
    assert "winget install --id A.B" in seen["text"] and "administrador" in seen["text"]
    assert seen["flags"] & 0x4 and seen["flags"] & 0x100 and seen["flags"] & 0x40000     # MB_YESNO, botón predeterminado «No», siempre visible
    monkeypatch.setattr(pw.u32, "MessageBoxW", lambda *a: 6, raising=False)
    assert pw.confirm_dialog("x", "y") is True
