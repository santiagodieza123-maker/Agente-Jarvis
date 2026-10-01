"""Recetas: secuencias de llamadas a herramientas que funcionaron, guardadas por el usuario desde el HUD para repetirlas SIN
llamar al LLM. Cada paso se vuelve a pasar por la política y las confirmaciones (una receta no concede permisos). Si una
precondición no se cumple, o un paso falla, no se improvisa: se informa y el usuario puede pedir a Jarvis que explore."""
from __future__ import annotations

import json
import re
from typing import Any

MAX_STEPS = 40
MAX_ARG_JSON = 4000
NAME_RE = re.compile(r"^[A-Za-z0-9áéíóúñÁÉÍÓÚÑ _.-]{1,60}$")
PARAM_RE = re.compile(r"\{\{([a-z][a-z0-9_]{0,19})\}\}")
PRECONDITION_TYPES = ("path_exists", "window_contains")


class RecipeError(ValueError):
    pass


def validate_name(name) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name.strip()):
        raise RecipeError("nombre inválido (1–60 caracteres: letras, números, espacio, '.', '_' y '-')")
    return name.strip()


def validate_steps(steps) -> list[dict]:
    if not isinstance(steps, list) or not steps:
        raise RecipeError("la receta no tiene pasos")
    if len(steps) > MAX_STEPS:
        raise RecipeError(f"máximo {MAX_STEPS} pasos")
    clean = []
    for s in steps:
        if not (isinstance(s, dict) and isinstance(s.get("tool"), str) and isinstance(s.get("args"), dict)):
            raise RecipeError("paso inválido")
        if len(json.dumps(s["args"], ensure_ascii=False)) > MAX_ARG_JSON:
            raise RecipeError(f"argumentos demasiado largos en {s['tool']}")
        clean.append({"tool": s["tool"], "args": s["args"]})
    return clean


def steps_from_calls(calls) -> list[dict]:
    """Pasos reproducibles de un episodio: solo las llamadas que se ejecutaron bien."""
    if not isinstance(calls, list):
        return []
    return [{"tool": c["tool"], "args": c["args"]} for c in calls if isinstance(c, dict) and c.get("ok") and isinstance(c.get("tool"), str) and isinstance(c.get("args"), dict)][:MAX_STEPS]


def _walk(v: Any, fn):
    if isinstance(v, str):
        return fn(v)
    if isinstance(v, dict):
        return {k: _walk(x, fn) for k, x in v.items()}
    if isinstance(v, list):
        return [_walk(x, fn) for x in v]
    return v


def extract_params(steps: list[dict]) -> list[str]:
    found: list[str] = []
    for s in steps:
        _walk(s["args"], lambda t: found.extend(m for m in PARAM_RE.findall(t) if m not in found) or t)
    return found


def substitute(args: dict, params: dict[str, str]) -> dict:
    def rep(t: str) -> str:
        def one(m):
            if m.group(1) not in params:
                raise RecipeError(f"falta el parámetro «{m.group(1)}»")
            return params[m.group(1)]
        return PARAM_RE.sub(one, t)
    return _walk(args, rep)


def validate_params(values, declared: list[str]) -> dict[str, str]:
    values = values if isinstance(values, dict) else {}
    out = {}
    for name in declared:
        v = values.get(name)
        if not isinstance(v, str) or len(v) > 2000:
            raise RecipeError(f"parámetro «{name}» inválido (texto de hasta 2000 caracteres)")
        out[name] = v
    return out


def validate_preconditions(items) -> list[dict]:
    if items in (None, []):
        return []
    if not isinstance(items, list) or len(items) > 10:
        raise RecipeError("precondiciones inválidas (máx. 10)")
    out = []
    for it in items:
        if not (isinstance(it, dict) and it.get("type") in PRECONDITION_TYPES):
            raise RecipeError(f"tipo de precondición inválido; admitidos: {', '.join(PRECONDITION_TYPES)}")
        key = "path" if it["type"] == "path_exists" else "text"
        v = it.get(key)
        if not isinstance(v, str) or not v.strip() or len(v) > 300:
            raise RecipeError(f"precondición «{it['type']}»: falta «{key}»")
        out.append({"type": it["type"], key: v.strip()})
    return out
