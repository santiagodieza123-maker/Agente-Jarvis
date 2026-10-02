"""Voz a texto para el HUD: recibe un fragmento de audio (WAV de unos segundos), lo transcribe con el modelo y devuelve el texto.
El texto es una entrada del usuario, como si lo hubiera escrito: pasa por la política y las confirmaciones igual que cualquier tarea.
El audio nunca se guarda en disco ni en el log. Con Whisper local (ajuste voice_local) no sale del equipo; si no, se envía a
Google (Gemini) para transcribirlo. Si se eligió local y falla, NO se recurre a Google: se informa del error."""
from __future__ import annotations

import asyncio
import base64
import binascii
import time
from collections import deque

from core.bus import EventBus
from core.llm.holder import LLMHolder, NoLLM

MAX_AUDIO_BYTES = 4 * 1024 * 1024            # ≈ 2 min de WAV mono a 16 kHz
MIMES = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/ogg", "audio/flac", "audio/aac"}
MAX_PER_MINUTE = 20
SILENCE = "[silencio]"


class VoiceHandlers:
    def __init__(self, bus: EventBus, audit, holder: LLMHolder, clock=time.monotonic, local=None, use_local=lambda: False):
        self.bus, self.audit, self.holder, self.clock = bus, audit, holder, clock
        self.local, self.use_local = local, use_local          # motor local (LocalWhisper) y si el usuario lo prefiere
        self._recent: deque = deque()

    def _out(self, rid: str, **kw) -> None:
        self.bus.publish("voice.transcript", {"id": rid, **kw})

    async def __call__(self, msg: dict) -> bool:
        if msg.get("type") != "voice.transcribe":
            return False
        rid = msg.get("id")
        rid = rid if isinstance(rid, str) and 0 < len(rid) <= 40 else "?"
        mime, raw = msg.get("mime", "audio/wav"), msg.get("audio")
        if mime not in MIMES:
            self._out(rid, error="formato de audio no admitido")
            return True
        if not isinstance(raw, str) or len(raw) > MAX_AUDIO_BYTES * 4 // 3 + 8:
            self._out(rid, error=f"audio inválido o de más de {MAX_AUDIO_BYTES // 1024 // 1024} MB")
            return True
        try:
            audio = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            self._out(rid, error="audio mal codificado")
            return True
        if len(audio) < 1000:
            self._out(rid, text="", silent=True)                     # fragmento diminuto: ni se envía
            return True
        engine = self.local if (self.local is not None and self.use_local()) else None
        if engine is None:                                            # el límite protege la cuota de la API; en local no hace falta
            now = self.clock()
            while self._recent and now - self._recent[0] > 60:
                self._recent.popleft()
            if len(self._recent) >= MAX_PER_MINUTE:
                self._out(rid, error="demasiadas transcripciones por minuto; espera un momento")
                return True
            self._recent.append(now)
        try:
            r = await asyncio.to_thread(engine.transcribe if engine else self.holder.transcribe, audio, mime)
        except NoLLM as e:
            self._out(rid, error=str(e))
            return True
        except Exception as e:  # noqa: BLE001 — LLMError ya viene sin la clave ni la petición
            self._out(rid, error=f"{type(e).__name__}: {str(e)[:160]}")
            return True
        text = r.text.strip()
        silent = (not text) or text.lower().strip("[]. ") == "silencio"
        self.audit.append("voice.transcribed", bytes=len(audio), engine="local" if engine else "gemini", chars=0 if silent else len(text))      # nunca el audio ni, aquí, el texto
        self._out(rid, text="" if silent else text[:2000], silent=silent)
        return True
