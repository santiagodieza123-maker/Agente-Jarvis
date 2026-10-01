import json
from datetime import date

from core.llm.holder import LLMHolder
from core.llm.provider import LLMProvider, LLMResponse
from core.usage import UsageStore


def test_accumulates_per_day_and_total_and_persists(tmp_path):
    day = [date(2026, 10, 1)]
    u = UsageStore(tmp_path / "u.json", today=lambda: day[0])
    u.add(10, 5); u.add(1, 1)
    day[0] = date(2026, 10, 2)
    u.add(100, 50)
    assert u.snapshot() == {"today": {"calls": 1, "input": 100, "output": 50}, "total": {"calls": 3, "input": 111, "output": 56}}
    u2 = UsageStore(tmp_path / "u.json", today=lambda: day[0])            # reinicio
    assert u2.snapshot()["total"]["calls"] == 3 and u2.snapshot()["today"]["input"] == 100
    day[0] = date(2026, 10, 3)
    assert u2.snapshot()["today"] == {"calls": 0, "input": 0, "output": 0}   # día nuevo, total intacto


def test_keeps_only_60_days_and_survives_garbage(tmp_path):
    n = [0]
    u = UsageStore(tmp_path / "u.json", today=lambda: date.fromordinal(739000 + n[0]))
    for n[0] in range(70):
        u.add(1, 1)
    assert len(u.days) == 60 and u.total["calls"] == 70
    for bad in ("no json", "[1]", '{"total": 5, "days": {"x": {"calls": -4}}}', '{"total": {"calls": true, "input": "7"}}'):
        (tmp_path / "b.json").write_text(bad)
        assert UsageStore(tmp_path / "b.json").total == {"calls": 0, "input": 0, "output": 0}


def test_holder_records_usage_and_never_fails_on_unwritable_store(tmp_path):
    class L(LLMProvider):
        def generate(self, *a, **k): return LLMResponse(text="x", input_tokens=7, output_tokens=3)
    h = LLMHolder(L(), UsageStore(tmp_path / "no" / "existe" / "u.json"))
    (tmp_path / "no").write_text("archivo, no carpeta")                    # la ruta no se puede crear
    h.generate("s", [], [])
    assert h.usage()["calls"] == 1 and h.usage()["total"]["input"] == 7
