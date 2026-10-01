import importlib.util
import subprocess
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("scan_secrets", Path(__file__).parent.parent / "tools" / "scan_secrets.py")
S = importlib.util.module_from_spec(spec)
sys.modules["scan_secrets"] = S
spec.loader.exec_module(S)


def test_repository_contains_no_secrets():
    assert S.scan(S.tracked(False)) == []


def test_scanner_detects_keys_and_local_values(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "REPO", tmp_path)
    (tmp_path / "a.txt").write_text("clave AQ." + "Z9" * 20 + " fin")
    (tmp_path / "b.txt").write_text("AIza" + "A" * 35)
    (tmp_path / "c.txt").write_text("valor-especial-123456")
    (tmp_path / "d.txt").write_text("AQ.test-key_0123456789abcdef y AQ.falsa_0123456789_abcdefghij")   # claves de prueba admitidas
    (tmp_path / "e.txt").write_text("nada")
    assert S.scan(["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"], secrets=["valor-especial-123456"]) == ["a.txt", "b.txt", "c.txt"]


def test_local_env_values_are_collected(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "REPO", tmp_path)
    assert S.local_secrets() == []
    (tmp_path / ".env").write_text("# c\nGEMINI_API_KEY=\"abcdefghijklmnop\"\nCORTO=1\n")
    assert S.local_secrets() == ["abcdefghijklmnop"]


def test_staged_scan_blocks_commit(tmp_path, monkeypatch):
    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True)
    git("init", "-q")
    monkeypatch.setattr(S, "REPO", tmp_path)
    (tmp_path / "x.txt").write_text("AQ." + "Z9" * 20)
    git("add", "x.txt")
    assert S.scan(S.tracked(True), secrets=[], staged=True) == ["x.txt"]
    assert S.main(["--staged"]) == 1
