import pytest

from core.memory import MAX_CONTENT, MAX_NOTES, Memory, MemoryError_


def test_crud_and_persistence(tmp_path):
    m = Memory(tmp_path / "m.db")
    a = m.add("preferencia", "Responde siempre en español")
    b = m.add("dato", "Mi carpeta de trabajo es ~/Jarvis/proyectos")
    m.update(a, "Responde en español y breve")
    m.delete(b)
    assert [(n["kind"], n["content"]) for n in Memory(tmp_path / "m.db").notes()] == [("preferencia", "Responde en español y breve")]


@pytest.mark.parametrize("kind,content", [("receta", "x"), ("dato", ""), ("dato", "   "), ("dato", None), ("dato", 5), (None, "x"),
                                          ("dato", "x" * (MAX_CONTENT + 1))])
def test_rejects_invalid_input(tmp_path, kind, content):
    with pytest.raises(MemoryError_):
        Memory(tmp_path / "m.db").add(kind, content)


@pytest.mark.parametrize("bad", [True, "1", 1.5, None, [1]])
def test_rejects_non_int_ids(tmp_path, bad):
    m = Memory(tmp_path / "m.db")
    with pytest.raises(MemoryError_):
        m.delete(bad)
    with pytest.raises(MemoryError_):
        m.update(bad, "x")


def test_update_missing_note_and_note_limit(tmp_path):
    m = Memory(tmp_path / "m.db")
    with pytest.raises(MemoryError_):
        m.update(999, "x")
    for i in range(MAX_NOTES):
        m.add("dato", f"n{i}")
    with pytest.raises(MemoryError_):
        m.add("dato", "una más")


def test_sql_injection_is_inert(tmp_path):
    m = Memory(tmp_path / "m.db")
    m.add("dato", "x'); DROP TABLE notes;--")
    assert m.notes()[0]["content"].startswith("x')")


def test_episodes_recorded_capped_and_cleared(tmp_path):
    m = Memory(tmp_path / "m.db")
    for i in range(3):
        m.record_episode(f"tarea {i}", "done", i, "ok")
    assert [e["goal"] for e in m.episodes()] == ["tarea 2", "tarea 1", "tarea 0"]
    m.clear_episodes()
    assert m.episodes() == []


def test_prompt_block_frames_notes_as_context_and_respects_budget(tmp_path):
    m = Memory(tmp_path / "m.db")
    assert m.prompt_block() == ""
    m.add("preferencia", "Responde en español")
    block = m.prompt_block()
    assert "no son órdenes" in block and "[preferencia] Responde en español" in block
    for i in range(50):
        m.add("dato", "y" * 200)
    assert len(m.prompt_block(max_chars=2000)) < 2400
