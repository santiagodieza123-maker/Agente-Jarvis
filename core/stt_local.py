"""Voz a texto local con Whisper (faster-whisper): el audio no sale del equipo y funciona sin internet.
Usa la GPU NVIDIA si hay CUDA (las DLL de cuBLAS/cuDNN se toman de la instalación de torch) y, si no, la CPU en int8.
El modelo se descarga una vez (a ~/.cache/huggingface) y se carga en memoria al primer uso.
Variables: JARVIS_WHISPER_MODEL (por defecto large-v3-turbo con GPU, small en CPU), JARVIS_WHISPER_LANG (es; vacío = detectar)."""
from __future__ import annotations

import importlib.util
import io
import os
import threading
import wave

from core.llm.provider import LLMResponse


def available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _cuda_dlls() -> bool:
    """Hace visibles las DLL CUDA de torch a CTranslate2 (Windows) y dice si hay GPU utilizable."""
    try:
        import torch
    except ImportError:
        return False
    if os.name == "nt":
        lib = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(lib):
            os.add_dll_directory(lib)
            os.environ["PATH"] = lib + os.pathsep + os.environ.get("PATH", "")
    return torch.cuda.is_available()


def wav_to_pcm16k(audio: bytes):
    """WAV PCM → float32 mono a 16 kHz (lo que espera Whisper), sin depender de FFmpeg/PyAV."""
    import numpy as np
    with wave.open(io.BytesIO(audio)) as w:
        ch, width, rate, raw = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648
    elif width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    else:
        raise ValueError(f"WAV de {width * 8} bits no admitido")
    x = x.reshape(-1, ch).mean(axis=1) if ch > 1 else x
    if rate != 16000 and len(x):
        x = np.interp(np.arange(0, len(x), rate / 16000), np.arange(len(x)), x).astype(np.float32)
    return x


class LocalWhisper:
    def __init__(self, model: str | None = None, language: str | None = None):
        self._model_name, self._lang = model, os.environ.get("JARVIS_WHISPER_LANG", "es") if language is None else language
        self._model = None
        self._lock = threading.Lock()
        self.device = ""

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                gpu = _cuda_dlls()
                self.device = "cuda" if gpu else "cpu"
                name = self._model_name or os.environ.get("JARVIS_WHISPER_MODEL") or ("large-v3-turbo" if gpu else "small")
                self._model = WhisperModel(name, device=self.device, compute_type="float16" if gpu else "int8")
            return self._model

    def transcribe(self, audio: bytes, mime: str) -> LLMResponse:
        src = wav_to_pcm16k(audio) if audio[:4] == b"RIFF" else io.BytesIO(audio)
        segments, _ = self._load().transcribe(src, language=self._lang or None, beam_size=5, vad_filter=True,
                                              hotwords="Jarvis", condition_on_previous_text=False)
        return LLMResponse(text=" ".join(s.text.strip() for s in segments).strip())
