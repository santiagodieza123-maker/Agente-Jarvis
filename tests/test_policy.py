from core.policy import Action, ActionClass as C, Decision as D, Origin as O, Policy

P = Policy(allowed_roots=["/home/u/docs"])


def test_read_allowed():
    assert P.evaluate(Action("fs.read", C.READ, O.USER, "/home/u/docs/a.txt")) is D.ALLOW


def test_path_outside_denied():
    assert P.evaluate(Action("fs.read", C.READ, O.USER, "/etc/passwd")) is D.DENY


def test_traversal_denied():
    assert P.evaluate(Action("fs.read", C.READ, O.USER, "/home/u/docs/../../etc/passwd")) is D.DENY


def test_destructive_needs_confirm():
    assert P.evaluate(Action("fs.delete", C.DESTRUCTIVE, O.USER, "/home/u/docs/a.txt")) is D.CONFIRM


def test_observed_content_cannot_write_silently():
    assert P.evaluate(Action("fs.write", C.WRITE_REVERSIBLE, O.OBSERVED, "/home/u/docs/a.txt")) is D.CONFIRM


def test_observed_content_cannot_elevate():
    assert P.evaluate(Action("broker.install", C.ELEVATED, O.OBSERVED)) is D.DENY
