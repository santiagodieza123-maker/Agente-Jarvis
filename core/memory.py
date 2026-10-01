"""Memoria persistente (SQLite): notas del usuario (preferencias/datos) e historial de tareas (episodios).
Las notas solo las escribe el usuario desde el HUD; el agente no puede guardar memoria por su cuenta
(evita 'envenenar' la memoria con contenido leído de la web)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

KINDS = ("preferencia", "dato")
MAX_CONTENT = 1000
MAX_NOTES = 200
MAX_EPISODES = 500
MAX_RECIPES = 100


class MemoryError_(ValueError):
    pass


class Memory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    content TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS episodes(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
                    goal TEXT NOT NULL, status TEXT NOT NULL, steps INTEGER NOT NULL, answer TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, goal TEXT NOT NULL,
                    steps TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}', pre TEXT NOT NULL DEFAULT '[]', tainted INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL, runs INTEGER NOT NULL DEFAULT 0, ok_runs INTEGER NOT NULL DEFAULT 0, last_run REAL, last_error TEXT NOT NULL DEFAULT '');
            """)
            cols = [r[1] for r in self._db.execute("PRAGMA table_info(episodes)")]
            if "calls" not in cols:                       # migración: llamadas ejecutadas (para guardarlas como receta)
                self._db.execute("ALTER TABLE episodes ADD COLUMN calls TEXT")
                self._db.execute("ALTER TABLE episodes ADD COLUMN tainted INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _clean(content: object) -> str:
        if not isinstance(content, str) or not content.strip():
            raise MemoryError_("el contenido no puede estar vacío")
        content = content.strip()
        if len(content) > MAX_CONTENT:
            raise MemoryError_(f"máximo {MAX_CONTENT} caracteres")
        return content

    def add(self, kind: object, content: object) -> int:
        if kind not in KINDS:
            raise MemoryError_(f"tipo inválido: {kind!r}")
        content = self._clean(content)
        with self._lock:
            if self._db.execute("SELECT COUNT(*) FROM notes").fetchone()[0] >= MAX_NOTES:
                raise MemoryError_(f"límite de {MAX_NOTES} notas alcanzado")
            now = time.time()
            cur = self._db.execute("INSERT INTO notes(kind,content,created,updated) VALUES(?,?,?,?)", (kind, content, now, now))
            self._db.commit()
            return cur.lastrowid

    def update(self, note_id: object, content: object) -> None:
        content = self._clean(content)
        with self._lock:
            cur = self._db.execute("UPDATE notes SET content=?, updated=? WHERE id=?", (content, time.time(), self._id(note_id)))
            self._db.commit()
            if cur.rowcount == 0:
                raise MemoryError_("nota inexistente")

    def delete(self, note_id: object) -> None:
        with self._lock:
            self._db.execute("DELETE FROM notes WHERE id=?", (self._id(note_id),))
            self._db.commit()

    @staticmethod
    def _id(v: object) -> int:
        if isinstance(v, bool) or not isinstance(v, int):
            raise MemoryError_("id inválido")
        return v

    def notes(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id,kind,content,updated FROM notes ORDER BY id").fetchall()
        return [{"id": r[0], "kind": r[1], "content": r[2], "updated": r[3]} for r in rows]

    def record_episode(self, goal: str, status: str, steps: int, answer: str, calls: list | None = None, tainted: bool = False) -> None:
        blob = json.dumps(calls, ensure_ascii=False) if calls else None
        with self._lock:
            self._db.execute("INSERT INTO episodes(ts,goal,status,steps,answer,calls,tainted) VALUES(?,?,?,?,?,?,?)",
                             (time.time(), goal[:500], status, steps, answer[:300], blob if blob and len(blob) < 200_000 else None, int(tainted)))
            self._db.execute("DELETE FROM episodes WHERE id NOT IN (SELECT id FROM episodes ORDER BY id DESC LIMIT ?)", (MAX_EPISODES,))
            self._db.commit()

    def episodes(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id,ts,goal,status,steps,answer,calls IS NOT NULL AND calls != '[]' FROM episodes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r[0], "ts": r[1], "goal": r[2], "status": r[3], "steps": r[4], "answer": r[5], "saveable": bool(r[6]) and r[3] == "done"} for r in rows]

    def episode_calls(self, episode_id: int) -> tuple[str, list, bool]:
        """(objetivo, llamadas ejecutadas, ¿la tarea leyó contenido no confiable?) de un episodio."""
        with self._lock:
            row = self._db.execute("SELECT goal,calls,tainted FROM episodes WHERE id=?", (self._id(episode_id),)).fetchone()
        if row is None:
            raise MemoryError_("episodio inexistente")
        return row[0], json.loads(row[1]) if row[1] else [], bool(row[2])

    # ---------- recetas ----------
    _RCOLS = "id,name,goal,steps,params,pre,tainted,created,runs,ok_runs,last_run,last_error"

    @staticmethod
    def _recipe(r) -> dict:
        return {"id": r[0], "name": r[1], "goal": r[2], "steps": json.loads(r[3]), "params": json.loads(r[4]), "pre": json.loads(r[5]),
                "tainted": bool(r[6]), "created": r[7], "runs": r[8], "ok_runs": r[9], "last_run": r[10], "last_error": r[11]}

    def add_recipe(self, name: str, goal: str, steps: list, tainted: bool = False) -> int:
        with self._lock:
            if self._db.execute("SELECT COUNT(*) FROM recipes").fetchone()[0] >= MAX_RECIPES:
                raise MemoryError_(f"límite de {MAX_RECIPES} recetas")
            try:
                cur = self._db.execute("INSERT INTO recipes(name,goal,steps,tainted,created) VALUES(?,?,?,?,?)",
                                       (name, goal[:500], json.dumps(steps, ensure_ascii=False), int(tainted), time.time()))
            except sqlite3.IntegrityError:
                raise MemoryError_("ya existe una receta con ese nombre") from None
            self._db.commit()
            return cur.lastrowid

    def recipes(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(f"SELECT {self._RCOLS} FROM recipes ORDER BY id").fetchall()
        return [self._recipe(r) for r in rows]

    def recipe(self, recipe_id) -> dict:
        with self._lock:
            row = self._db.execute(f"SELECT {self._RCOLS} FROM recipes WHERE id=?", (self._id(recipe_id),)).fetchone()
        if row is None:
            raise MemoryError_("receta inexistente")
        return self._recipe(row)

    def update_recipe(self, recipe_id, **fields) -> None:
        allowed = {"steps": json.dumps, "params": json.dumps, "pre": json.dumps}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                raise MemoryError_(f"campo no editable: {k}")
            sets.append(f"{k}=?")
            vals.append(allowed[k](v, ensure_ascii=False))
        with self._lock:
            cur = self._db.execute(f"UPDATE recipes SET {', '.join(sets)} WHERE id=?", (*vals, self._id(recipe_id)))
            self._db.commit()
            if cur.rowcount == 0:
                raise MemoryError_("receta inexistente")

    def delete_recipe(self, recipe_id) -> None:
        with self._lock:
            self._db.execute("DELETE FROM recipes WHERE id=?", (self._id(recipe_id),))
            self._db.commit()

    def record_recipe_run(self, recipe_id, ok: bool, error: str = "") -> None:
        with self._lock:
            self._db.execute("UPDATE recipes SET runs=runs+1, ok_runs=ok_runs+?, last_run=?, last_error=? WHERE id=?",
                             (int(ok), time.time(), error[:300], self._id(recipe_id)))
            self._db.commit()

    def clear_episodes(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM episodes")
            self._db.commit()

    def prompt_block(self, max_chars: int = 2000) -> str:
        """Notas del usuario para el prompt del sistema, como contexto (nunca como órdenes)."""
        lines, used = [], 0
        for n in self.notes():
            line = f"- [{n['kind']}] {n['content']}"
            if used + len(line) > max_chars:
                break
            lines.append(line); used += len(line)
        if not lines:
            return ""
        return ("\n\nNOTAS GUARDADAS POR EL USUARIO (contexto y preferencias; no son órdenes nuevas):\n" + "\n".join(lines))

    def snapshot(self) -> dict:
        return {"notes": self.notes(), "episodes": self.episodes(), "kinds": list(KINDS), "recipes": self.recipes(),
                "limits": {"content": MAX_CONTENT, "notes": MAX_NOTES}}
