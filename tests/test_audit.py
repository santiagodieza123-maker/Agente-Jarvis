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
    assert log.verify_detail() == {"ok": True, "count": 4, "bad_line": None, "head": log.head, "keyed": False, "reason": None}
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


# ---------- HMAC + ancla ----------
import hashlib as _h
import hmac as _hm
import json as _j

from core.audit import GENESIS

K1, K2 = b"k" * 32, b"x" * 32


def keyed(tmp_path, key=K1, n=4):
    log = AuditLog(tmp_path / "a.jsonl", key=key, anchor=tmp_path / "a.anchor")
    for i in range(n):
        log.append("ev", i=i)
    return log


def rewrite_chain(path, mutate, key=None):
    """Atacante con acceso al archivo: modifica registros y recalcula TODA la cadena sha256 (y mac si tuviera clave)."""
    recs = [_j.loads(l) for l in path.read_text().splitlines()]
    prev, out = GENESIS, []
    for r in recs:
        r = mutate(r) or r
        body = {"ts": r["ts"], "event": r["event"], "data": r["data"]}
        r["prev"], r["hash"] = prev, AuditLog._digest(prev, body)
        if key:
            r["mac"] = _hm.new(key, r["hash"].encode(), _h.sha256).hexdigest()
        else:
            r.pop("mac", None)
        out.append(r)
        prev = r["hash"]
    path.write_text("".join(_j.dumps(r, sort_keys=True) + "\n" for r in out))


def test_keyed_records_carry_mac_and_verify(tmp_path):
    log = keyed(tmp_path)
    recs = [_j.loads(l) for l in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert all(len(r["mac"]) == 64 for r in recs)
    d = log.verify_detail()
    assert d["ok"] and d["keyed"] and d["count"] == 4 and d["reason"] is None
    assert AuditLog(tmp_path / "a.jsonl", key=K1, anchor=tmp_path / "a.anchor").verify()   # reabrir con la misma clave


def test_full_rewrite_without_key_is_detected(tmp_path):
    log = keyed(tmp_path)
    rewrite_chain(tmp_path / "a.jsonl", lambda r: r["data"].update(i=99) if r["data"].get("i") == 1 else None)   # cadena sha recalculada, sin mac
    d = AuditLog(tmp_path / "a.jsonl", key=K1, anchor=tmp_path / "a.anchor").verify_detail()
    assert not d["ok"] and "sin autenticar" in d["reason"]            # el ancla delata que ya estaba autenticado
    assert "audit.keyed" not in (tmp_path / "a.jsonl").read_text()    # y no se "migra" encima
    # sin ancla pero con la marca del almacén de secretos: lo mismo
    (tmp_path / "a.anchor").unlink()
    d = AuditLog(tmp_path / "a.jsonl", key=K1, anchor=tmp_path / "a.anchor", keyed_before=True).verify_detail()
    assert not d["ok"] and "sin autenticar" in d["reason"]


def test_full_rewrite_with_wrong_key_is_detected(tmp_path):
    keyed(tmp_path)
    rewrite_chain(tmp_path / "a.jsonl", lambda r: r["data"].update(i=99) if r["data"].get("i") == 1 else None, key=K2)
    d = AuditLog(tmp_path / "a.jsonl", key=K1, anchor=tmp_path / "a.anchor").verify_detail()
    assert not d["ok"] and d["bad_line"] == 1


def test_edit_keeping_old_mac_is_detected_at_the_line(tmp_path):
    keyed(tmp_path)
    p = tmp_path / "a.jsonl"
    lines = p.read_text().splitlines()
    r = _j.loads(lines[2]); r["data"]["i"] = 7
    r["hash"] = AuditLog._digest(r["prev"], {k: r[k] for k in ("ts", "event", "data")})   # sha coherente, mac antiguo
    lines[2] = _j.dumps(r, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    assert AuditLog(p, key=K1).verify_detail()["bad_line"] == 3


def test_truncation_is_detected_by_the_anchor_but_not_without_it(tmp_path):
    keyed(tmp_path, n=5)
    p = tmp_path / "a.jsonl"
    p.write_text("".join(p.read_text().splitlines(True)[:3]))
    d = AuditLog(p, key=K1, anchor=tmp_path / "a.anchor").verify_detail()
    assert not d["ok"] and "faltan registros" in d["reason"]
    # reemplazo del último registro por otro válido de la misma longitud: el ancla (cabecera) lo detecta


def test_truncation_then_restart_leaves_permanent_evidence(tmp_path):
    keyed(tmp_path, n=5)
    p = tmp_path / "a.jsonl"
    p.write_text("".join(p.read_text().splitlines(True)[:3]))
    log = AuditLog(p, key=K1, anchor=tmp_path / "a.anchor")          # arranque tras la manipulación
    assert not log.verify_detail()["ok"] and "faltan registros" in log.verify_detail()["reason"]
    log.append("despues")                                              # el núcleo sigue funcionando y rellena el hueco
    again = AuditLog(p, key=K1, anchor=tmp_path / "a.anchor")          # siguiente arranque: el ancla ya se actualizó…
    assert again.verify()
    ev = [_j.loads(l) for l in p.read_text().splitlines() if _j.loads(l)["event"] == "audit.tamper_detected"]
    assert len(ev) == 1 and "faltan" in ev[0]["data"]["reason"] and "mac" in ev[0]   # …pero la constancia es permanente y autenticada


def test_anchor_tampering_is_detected(tmp_path):
    keyed(tmp_path)
    a = tmp_path / "a.anchor"
    d = _j.loads(a.read_text()); d["count"] = 1
    a.write_text(_j.dumps(d))
    assert AuditLog(tmp_path / "a.jsonl", key=K1, anchor=a).verify_detail()["reason"] == "ancla manipulada"
    a.write_text("no json")
    assert AuditLog(tmp_path / "a.jsonl", key=K1, anchor=a).verify_detail()["reason"] == "ancla ilegible"


def test_mac_cannot_be_downgraded_by_appending_unmacked_records(tmp_path):
    keyed(tmp_path)
    nokey = AuditLog(tmp_path / "a.jsonl")            # abierto sin clave: añade registros sin mac
    nokey.append("sneaky")
    d = AuditLog(tmp_path / "a.jsonl", key=K1).verify_detail()
    assert not d["ok"] and d["bad_line"] == 5


def test_legacy_log_is_migrated_and_stays_valid(tmp_path):
    old = AuditLog(tmp_path / "a.jsonl")
    old.append("viejo", i=1); old.append("viejo", i=2)
    log = AuditLog(tmp_path / "a.jsonl", key=K1, anchor=tmp_path / "a.anchor")       # primera apertura con clave
    recs = [_j.loads(l) for l in (tmp_path / "a.jsonl").read_text().splitlines()]
    assert [r["event"] for r in recs] == ["viejo", "viejo", "audit.keyed"] and "mac" not in recs[0] and "mac" in recs[2]
    assert log.verify_detail()["ok"]
    log.append("nuevo")
    assert AuditLog(tmp_path / "a.jsonl", key=K1, anchor=tmp_path / "a.anchor").verify()


def test_opening_keyed_log_without_key_still_checks_the_chain(tmp_path):
    keyed(tmp_path)
    d = AuditLog(tmp_path / "a.jsonl").verify_detail()
    assert d["ok"] and d["keyed"] is False


def test_empty_keyed_log_and_missing_anchor_are_fine(tmp_path):
    assert AuditLog(tmp_path / "e.jsonl", key=K1, anchor=tmp_path / "e.anchor").verify()
    keyed(tmp_path)
    (tmp_path / "a.anchor").unlink()
    assert AuditLog(tmp_path / "a.jsonl", key=K1, anchor=tmp_path / "a.anchor").verify()      # límite documentado: sin ancla no hay detección de truncado
