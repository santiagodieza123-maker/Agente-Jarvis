"""Proveedor intercambiable en caliente: el orquestador conserva una referencia estable mientras el HUD cambia modelo o clave."""
from __future__ import annotations

import time
from collections import deque

from core.llm.provider import LLMProvider, LLMResponse


class NoLLM(RuntimeError):
    pass


class LLMHolder(LLMProvider):
    def __init__(self, inner: LLMProvider | None = None, store=None):
        self.inner = inner
        self.store = store                                          # UsageStore opcional: consumo persistente
        self.latencies: deque = deque(maxlen=50)                    # ms de las últimas llamadas
        self.errors = 0
        self.on_wait = None                                         # aviso (segundos, motivo) mientras el proveedor espera
        self.calls = self.input_tokens = self.output_tokens = 0     # consumo de la sesión

    def generate(self, system, messages, tools, image_png=None) -> LLMResponse:
        inner = self.inner                                          # una sola lectura: el cambio puede ocurrir en otro hilo
        if inner is None:
            raise NoLLM("sin clave de API configurada")
        if hasattr(inner, "on_wait"):
            inner.on_wait = self.on_wait
        t0 = time.perf_counter()
        try:
            r = inner.generate(system, messages, tools, image_png)
        except Exception:
            self.errors += 1
            raise
        self.latencies.append((time.perf_counter() - t0) * 1000)
        self.calls += 1
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        if self.store is not None:
            self.store.add(r.input_tokens, r.output_tokens)
        return r

    def usage(self) -> dict:
        u = {"calls": self.calls, "input": self.input_tokens, "output": self.output_tokens}        # de la sesión
        return {**u, **self.store.snapshot()} if self.store is not None else u

    def transcribe(self, audio: bytes, mime: str) -> LLMResponse:
        inner = self.inner
        if inner is None:
            raise NoLLM("sin clave de API configurada")
        if not hasattr(inner, "transcribe"):
            raise NoLLM("el proveedor actual no transcribe voz")
        if hasattr(inner, "on_wait"):
            inner.on_wait = self.on_wait
        t0 = time.perf_counter()
        try:
            r = inner.transcribe(audio, mime)
        except Exception:
            self.errors += 1
            raise
        self.latencies.append((time.perf_counter() - t0) * 1000)
        self.calls += 1
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        if self.store is not None:
            self.store.add(r.input_tokens, r.output_tokens)
        return r
