"""Mensajes `recipes.*` del HUD: guardar una tarea ya hecha como receta, parametrizarla, fijar precondiciones y ejecutarla sin LLM."""
from __future__ import annotations

import re

from core.bus import EventBus
from core.memory import Memory, MemoryError_
from core.recipes import (PARAM_RE, RecipeError, extract_params, steps_from_calls, validate_name, validate_params,
                          validate_preconditions, validate_steps)

PARAM_NAME = re.compile(r"^[a-z][a-z0-9_]{0,19}$")


class RecipeHandlers:
    def __init__(self, bus: EventBus, audit, memory: Memory, orch, handlers, tools: dict, is_enabled, allowed, publish_memory):
        self.bus, self.audit, self.memory, self.orch, self.handlers = bus, audit, memory, orch, handlers
        self.tools, self.is_enabled, self.allowed, self.publish_memory = tools, is_enabled, allowed, publish_memory

    def _notice(self, level: str, text: str) -> None:
        self.bus.publish("ui.notice", {"level": level, "text": text})

    async def __call__(self, msg: dict) -> bool:
        kind = msg.get("type")
        if not isinstance(kind, str) or not kind.startswith("recipes."):
            return False
        try:
            if kind == "recipes.save":
                goal, calls, tainted = self.memory.episode_calls(msg.get("episode_id"))
                steps = validate_steps(steps_from_calls(calls))
                rid = self.memory.add_recipe(validate_name(msg.get("name")), goal, steps, tainted)
                self.audit.append("recipe.saved", id=rid, name=msg.get("name"), steps=len(steps), tainted=tainted)
                self._notice("info", f"Receta guardada con {len(steps)} pasos" + (" (⚠ la tarea leyó contenido no confiable: revisa los pasos)" if tainted else ""))
            elif kind == "recipes.delete":
                self.memory.delete_recipe(msg.get("id"))
                self.audit.append("recipe.deleted", id=msg.get("id"))
            elif kind == "recipes.param":
                self._param(msg)
            elif kind == "recipes.set_preconditions":
                pre = validate_preconditions(msg.get("items"))
                self.memory.update_recipe(msg.get("id"), pre=pre)
                self.audit.append("recipe.preconditions", id=msg.get("id"), items=pre)
            elif kind == "recipes.run":
                await self._run(msg)
            elif kind != "recipes.list":
                return True
        except (RecipeError, MemoryError_) as e:
            self._notice("error", str(e))
        finally:
            self.publish_memory()
        return True

    def _param(self, msg: dict) -> None:
        r = self.memory.recipe(msg.get("id"))
        i, arg, name = msg.get("step"), msg.get("arg"), msg.get("name")
        if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(r["steps"]):
            raise RecipeError("paso inexistente")
        if not isinstance(name, str) or not PARAM_NAME.match(name):
            raise RecipeError("nombre de parámetro inválido (a-z, 0-9 y _, empezando por letra, máx. 20)")
        args = r["steps"][i]["args"]
        if not isinstance(arg, str) or not isinstance(args.get(arg), str):
            raise RecipeError("solo se pueden parametrizar argumentos de texto")
        params = dict(r["params"])
        params[name] = args[arg]                                           # el valor original queda como valor por defecto
        args[arg] = "{{" + name + "}}"
        self.memory.update_recipe(r["id"], steps=r["steps"], params=params)
        self.audit.append("recipe.param", id=r["id"], step=i, arg=arg, name=name)

    async def _preconditions(self, r: dict) -> str | None:
        """Motivo por el que NO se puede ejecutar, o None."""
        for st in r["steps"]:
            t = self.tools.get(st["tool"])
            if t is None or not self.is_enabled(t.name):
                return f"la herramienta {st['tool']} no está disponible o está deshabilitada"
        for p in r["pre"]:
            if p["type"] == "path_exists":
                from pathlib import Path
                if not self.allowed(p["path"]) or not Path(p["path"]).exists():
                    return f"precondición no cumplida: no existe {p['path']} (o está fuera de las carpetas permitidas)"
            elif p["type"] == "window_contains":
                gw = self.tools.get("gui.windows")
                if gw is None:
                    return "precondición de ventana: las herramientas gui no están disponibles"
                if p["text"].lower() not in str(await gw.run()).lower():
                    return f"precondición no cumplida: no hay ninguna ventana con «{p['text']}»"
        return None

    async def _run(self, msg: dict) -> None:
        r = self.memory.recipe(msg.get("id"))
        declared = extract_params(r["steps"])
        given = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        values = validate_params({n: given.get(n, r["params"].get(n)) for n in declared}, declared)

        async def job():
            why = await self._preconditions(r)
            if why:
                self.memory.record_recipe_run(r["id"], False, why)
                self.audit.append("recipe.skipped", id=r["id"], reason=why)
                self._notice("error", f"{r['name']}: {why}. Puedes pedirle a Jarvis que lo explore de nuevo con el objetivo «{r['goal'][:80]}».")
                self.bus.publish("plan.updated", {"text": f"Receta «{r['name']}» no ejecutada: {why}"})
                return
            res = await self.orch.replay(r["steps"], values, f"Receta «{r['name']}»")
            self.memory.record_recipe_run(r["id"], res["ok"], res["error"])
            if res["ok"]:
                self._notice("info", f"Receta «{r['name']}» completada ({res['ran']} pasos, sin usar el modelo)")
                self.bus.publish("plan.updated", {"text": f"Receta «{r['name']}» completada."})
            else:
                self._notice("error", f"Receta «{r['name']}» falló en el paso {res['failed_at']}: {res['error'][:160]}")
                self.bus.publish("plan.updated", {"text": f"Receta «{r['name']}» falló en el paso {res['failed_at']}. Puedes pedirle a Jarvis que lo resuelva de nuevo."})
            self.publish_memory()

        await self.handlers.start_job(f"Receta «{r['name']}»", job)
