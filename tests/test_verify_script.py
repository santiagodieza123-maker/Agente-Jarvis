import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("verify_windows", Path(__file__).parent.parent / "tools" / "verify_windows.py")
v = importlib.util.module_from_spec(spec)
sys.modules["verify_windows"] = v
spec.loader.exec_module(v)


def test_run_checks_captures_exceptions_and_summarizes():
    def boom():
        raise RuntimeError("x")
    res = v.run_checks([("ok", lambda: (v.PASS, "bien")), ("boom", boom), ("w", lambda: (v.WARN, "ojo"))])
    assert [r["status"] for r in res] == [v.PASS, v.FAIL, v.WARN]
    text = v.summarize(res)
    assert "RuntimeError" in text and "RESUMEN: 1 OK, 1 FAIL, 1 WARN, 0 SKIP" in text


def test_all_checks_registered_with_unique_names():
    names = [n for n, _ in v.CHECKS]
    assert len(names) == len(set(names)) >= 9
