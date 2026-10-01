"""Configuración persistente (~/.jarvis/settings.json) y almacén de la clave de API.
La clave nunca se devuelve al HUD ni se escribe en el log: solo se informa de si existe y de sus 4 últimos caracteres."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

ACCENTS = ("cian", "ámbar", "verde", "magenta")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")      # va dentro de la URL de la API: sin '/', '?' ni '#'
_KEY = re.compile(r"^[A-Za-z0-9._-]{16,256}$")

# nombre -> (tipo, mínimo, máximo, requiere reinicio)
SPEC: dict[str, tuple] = {
    "model": (str, None, None, False),
    "max_steps": (int, 1, 50, False),
    "max_failures": (int, 1, 10, False),
    "approval_timeout": (int, 10, 600, False),
    "token_budget": (int, 0, 5_000_000, False),
    "browser_headed": (bool, None, None, True),
    "accent": (str, None, None, False),
}
DEFAULTS = {"model": "gemini-3.1-flash-lite", "max_steps": 15, "max_failures": 3, "approval_timeout": 120,
            "token_budget": 0, "browser_headed": False, "accent": "cian"}


class SettingsError(ValueError):
    pass


def _check(name: str, v):
    if name not in SPEC:
        raise SettingsError(f"ajuste desconocido: {name}")
    typ, lo, hi, _ = SPEC[name]
    if typ is bool:
        if not isinstance(v, bool):
            raise SettingsError(f"{name} debe ser verdadero/falso")
    elif typ is int:
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise SettingsError(f"{name} debe ser un entero entre {lo} y {hi}")
    elif name == "model":
        if not isinstance(v, str) or not _MODEL.match(v):
            raise SettingsError("modelo inválido (letras, números, '.', '_' y '-', máx. 64)")
    elif name == "accent":
        if v not in ACCENTS:
            raise SettingsError(f"color inválido; opciones: {', '.join(ACCENTS)}")
    return v


def _atomic_write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class SettingsStore:
    def __init__(self, path: str | Path, defaults: dict | None = None):
        self.path = Path(path)
        self.values = {**DEFAULTS, **(defaults or {})}
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        for k, v in (saved.items() if isinstance(saved, dict) else ()):
            try:
                self.values[k] = _check(k, v)
            except SettingsError:
                pass                        # valor guardado inválido o de otra versión: se ignora

    def update(self, changes) -> dict:
        """Todo o nada. Devuelve solo lo que cambió realmente."""
        if not isinstance(changes, dict) or not changes:
            raise SettingsError("nada que cambiar")
        clean = {k: _check(k, v) for k, v in changes.items()}
        changed = {k: v for k, v in clean.items() if self.values.get(k) != v}
        if changed:
            self.values.update(changed)
            _atomic_write(self.path, json.dumps(self.values, indent=2, ensure_ascii=False))
        return changed

    def spec(self) -> dict:
        return {k: {"min": lo, "max": hi, "restart": rs} for k, (_, lo, hi, rs) in SPEC.items() if lo is not None or rs}


class SecretStore:
    """Credential Manager (vía `keyring`) cuando está disponible; si no, un archivo 0600 en la carpeta de Jarvis."""

    SERVICE, NAME = "jarvis", "gemini_api_key"

    def __init__(self, path: str | Path, keyring_mod="auto"):
        self.path = Path(path)
        self._kr = self._find_keyring() if keyring_mod == "auto" else keyring_mod

    @staticmethod
    def _find_keyring():
        try:
            import keyring
            if "fail" in type(keyring.get_keyring()).__name__.lower():
                return None                 # sin backend real (p. ej. Linux sin servicio de secretos)
            return keyring
        except Exception:
            return None

    @property
    def backend(self) -> str:
        return "keyring" if self._kr else "archivo"

    @staticmethod
    def validate(key) -> str:
        if not isinstance(key, str) or not _KEY.match(key.strip()):
            raise SettingsError("clave inválida (16–256 caracteres: letras, números, '.', '_' y '-')")
        return key.strip()

    def _file_get(self) -> str | None:
        try:
            v = json.loads(self.path.read_text(encoding="utf-8")).get(self.NAME)
            return v if isinstance(v, str) and v else None
        except (OSError, ValueError, AttributeError):
            return None

    def get(self) -> str | None:
        if self._kr:
            try:
                v = self._kr.get_password(self.SERVICE, self.NAME)
                if v:
                    return v
            except Exception:
                pass
        return self._file_get()

    def set(self, key: str) -> None:
        key = self.validate(key)
        if self._kr:
            try:
                self._kr.set_password(self.SERVICE, self.NAME, key)
                self._file_clear()
                return
            except Exception:
                pass                        # el almacén del sistema falló: se usa el archivo
        _atomic_write(self.path, json.dumps({self.NAME: key}), 0o600)

    def _file_clear(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass

    def clear(self) -> None:
        if self._kr:
            try:
                self._kr.delete_password(self.SERVICE, self.NAME)
            except Exception:
                pass
        self._file_clear()

    @staticmethod
    def hint(key: str) -> str:
        return "…" + key[-4:]
