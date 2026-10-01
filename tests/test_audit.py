import json

from core.audit import AuditLog


def test_chain_verifies(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.append("action.started", tool="fs.read")
    log.append("action.finished", ok=True)
    assert log.verify()
    assert AuditLog(tmp_path / "a.jsonl").verify()  # reabrir conserva la cadena


def test_tamper_detected(tmp_path):
    p = tmp_path / "a.jsonl"
    log = AuditLog(p)
    log.append("x", n=1)
    log.append("y", n=2)
    lines = p.read_text().splitlines()
    rec = json.loads(lines[0]); rec["data"]["n"] = 99
    p.write_text(json.dumps(rec, sort_keys=True) + "\n" + lines[1] + "\n")
    assert not log.verify()
