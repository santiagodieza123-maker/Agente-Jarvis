"""Mensajes `config.*` del HUD: ajustes, clave de API y prueba de conexión. Cada cambio responde con una instantánea completa."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Callable

from core.bus import EventBus
from core.llm.holder import LLMHolder
from core.settings import ACCENTS, SecretStore, SettingsError, SettingsStore, SPEC

KILL_HOTKEY = "Ctrl+Shift+F10"      # fijado por el watchdog (proceso aparte): el HUD solo lo muestra


class ConfigHandlers:
    def __init__(self, bus: EventBus, audit, store: SettingsStore, secrets: SecretStore, holder: LLMHolder,
                 apply: Callable[[bool], None], env_key: Callable[[], str | None] = lambda: os.environ.get("GEMINI_API_KEY")):
        self.bus, self.audit, self.store, self.secrets, self.holder, self.apply, self.env_key = bus, audit, store, secrets, holder, apply, env_key
        self._testing = False
        self.voice_local_ready = False                                # hay motor Whisper instalado (lo fija app.wire)

    def key(self) -> str | None:
        """Prioridad: la clave guardada desde el HUD; si no hay, la del entorno / .env."""
        return self.secrets.get() or self.env_key() or None

    def snapshot(self) -> dict:
        stored, env = self.secrets.get(), self.env_key()
        key = stored or env
        return {
            "values": dict(self.store.values), "spec": self.store.spec(), "accents": list(ACCENTS),
            "restart": [k for k, s in SPEC.items() if s[3]],
            "api_key": {"configured": bool(key), "source": "almacén" if stored else ("entorno" if env else ""),
                        "hint": SecretStore.hint(key) if key else "", "backend": self.secrets.backend},
            "usage": self.holder.usage(), "llm_ready": self.holder.inner is not None,
            "fixed": {"kill_hotkey": KILL_HOTKEY}, "voice_local_ready": self.voice_local_ready,
        }

    def publish(self) -> None:
        self.bus.publish("config.changed", self.snapshot())

    def _notice(self, level: str, text: str) -> None:
        self.bus.publish("ui.notice", {"level": level, "text": text})

    async def __call__(self, msg: dict) -> bool:
        kind = msg.get("type")
        if not isinstance(kind, str) or not kind.startswith("config."):
            return False
        try:
            if kind == "config.set":
                changed = self.store.update(msg.get("values"))
                if changed:
                    self.audit.append("config.set", changed=changed)
                    self.apply("model" in changed)
                    if any(SPEC[k][3] for k in changed):
                        self._notice("info", "Algunos cambios se aplican al reiniciar Jarvis")
            elif kind == "config.set_api_key":
                self.secrets.set(msg.get("key"))                          # valida; nunca se registra el valor
                self.audit.append("config.set_api_key", backend=self.secrets.backend)
                self.apply(True)
                self._notice("info", "Clave guardada")
            elif kind == "config.clear_api_key":
                self.secrets.clear()
                self.audit.append("config.clear_api_key")
                self.apply(True)
                self._notice("info", "Clave guardada eliminada" + ("; se usa la del entorno" if self.env_key() else ""))
            elif kind == "config.test_llm":
                await self._test()
            elif kind != "config.get":
                return True
        except SettingsError as e:
            self._notice("error", str(e))
        finally:
            self.publish()
        return True

    async def _test(self) -> None:
        if self._testing:
            self._notice("info", "Ya hay una prueba en curso")
            return
        if self.holder.inner is None:
            self._notice("error", "No hay clave de API configurada")
            return
        self._testing = True
        t0 = time.monotonic()
        try:
            r = await asyncio.to_thread(self.holder.generate, "Responde solo con la palabra: ok",
                                        [{"role": "user", "content": "ping"}], [])
            ms = int((time.monotonic() - t0) * 1000)
            self._notice("info", f"Conexión correcta · {self.store.values['model']} · {ms} ms · {r.input_tokens + r.output_tokens} tokens")
        except Exception as e:                                           # LLMError ya viene sin la clave ni la petición
            self._notice("error", f"La prueba falló: {type(e).__name__}: {str(e)[:200]}")
        finally:
            self._testing = False
