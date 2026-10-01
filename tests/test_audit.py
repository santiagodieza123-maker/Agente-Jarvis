import json

import pytest

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


def fill(log):
    log.append("task.started", goal="abre notas")
    log.append("action.evaluated", tool="fs.read", decision="allow")
    log.append("action.denied", tool="fs.delete")
    log.append("task.finished", status="done")


def test_query_newest_first_with_seq_and_filters(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl"); fill(log)
    q = log.query()
    assert [r["event"] for r in q["records"]] == ["task.finished", "action.denied", "action.evaluated", "task.started"]
    assert [r["seq"] for r in q["records"]] == [4, 3, 2, 1] and q["total"] == 4 and q["head"] == log.head
    assert [r["event"] for r in log.query(event="action.denied")["records"]] == ["action.denied"]
    assert log.query(event="action.denied")["event_types"] == sorted({"task.started", "action.evaluated", "action.denied", "task.finished"})
    assert [r["event"] for r in log.query(text="FS.READ")["records"]] == ["action.evaluated"]     # sin distinguir mayúsculas
    assert log.query(text="nada-por-aqui")["records"] == []
    assert len(log.query(limit=2)["records"]) == 2 and log.query(limit=2)["matched"] == 4


def test_verify_detail_reports_first_broken_line(tmp_path):
    p = tmp_path / "a.jsonl"; log = AuditLog(p); fill(log)
    assert log.verify_detail() == {"ok": True, "count": 4, "bad_line": None, "head": log.head}
    lines = p.read_text().splitlines()
    rec = json.loads(lines[2]); rec["data"]["tool"] = "otra"
    lines[2] = json.dumps(rec, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    d = log.verify_detail()
    assert d["ok"] is False and d["bad_line"] == 3 and d["count"] == 2


def test_deleting_and_reordering_lines_is_detected(tmp_path):
    p = tmp_path / "a.jsonl"; log = AuditLog(p); fill(log)
    lines = p.read_text().splitlines()
    p.write_text("\n".join(lines[:1] + lines[2:]) + "\n")                 # falta el registro 2
    assert log.verify_detail()["bad_line"] == 2
    p.write_text("\n".join([lines[1], lines[0]] + lines[2:]) + "\n")      # orden cambiado
    assert log.verify_detail()["bad_line"] == 1


def test_corrupt_lines_never_crash_startup_or_verify(tmp_path):
    p = tmp_path / "a.jsonl"; log = AuditLog(p); fill(log)
    with p.open("a") as f:
        f.write('{"event": "x", "da')                                    # escritura parcial sin salto de línea
    reopened = AuditLog(p)                                               # antes: JSONDecodeError al arrancar
    assert reopened.head == log.head
    reopened.append("after.crash")                                       # no se pega a la línea parcial
    d = reopened.verify_detail()
    assert d["ok"] is False and d["bad_line"] == 5
    q = reopened.query()
    assert any(r["event"] == "(línea corrupta)" for r in q["records"]) and q["records"][0]["event"] == "after.crash"


@pytest.mark.parametrize("junk", ["[1,2,3]", "null", '{"hash": 5}', '{"ts":"x"}', "\x00\x01", '{"event":"e","data":[],"ts":1,"prev":"","hash":""}'])
def test_malformed_but_valid_json_lines_are_flagged_not_fatal(tmp_path, junk):
    p = tmp_path / "a.jsonl"; log = AuditLog(p); fill(log)
    with p.open("a") as f:
        f.write(junk + "\n")
    assert AuditLog(p).verify_detail()["bad_line"] == 5 and AuditLog(p).query()["total"] == 5


def test_large_records_are_clipped_for_display_only(tmp_path):
    p = tmp_path / "a.jsonl"; log = AuditLog(p)
    log.append("action.evaluated", tool="fs.write", args={"content": "x" * 50_000})
    r = log.query()["records"][0]
    assert r.get("clipped") is True and len(json.dumps(r)) < 3000
    assert len(p.read_text()) > 50_000 and log.verify()                  # el log en disco está completo


def test_on_append_hook_receives_seq_and_blank_log_is_ok(tmp_path):
    got = []
    log = AuditLog(tmp_path / "x" / "a.jsonl", on_append=got.append)
    assert log.verify_detail()["ok"] and log.query()["records"] == []
    log.append("a"); log.append("b")
    assert [g["seq"] for g in got] == [1, 2] and log.query()["records"][0]["seq"] == 2


def test_truncated_window_when_file_is_large(tmp_path, monkeypatch):
    import core.audit as audit
    monkeypatch.setattr(audit, "MAX_READ_BYTES", 600)
    log = AuditLog(tmp_path / "a.jsonl")
    for i in range(30):
        log.append("evt", i=i)
    q = log.query(limit=500)
    assert q["truncated"] is True and 0 < len(q["records"]) < 30
    assert q["records"][0]["data"]["i"] == 29 and q["records"][0]["seq"] == 30      # seq sigue siendo la línea real
    assert log.verify()                                                              # verificar sí recorre todo
