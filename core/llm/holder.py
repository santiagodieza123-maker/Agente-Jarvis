"""Proveedor intercambiable en caliente: el orquestador conserva una referencia estable mientras el HUD cambia modelo o clave."""
from __future__ import annotations

from core.llm.provider import LLMProvider, LLMResponse


class NoLLM(RuntimeError):
    pass


class LLMHolder(LLMProvider):
    def __init__(self, inner: LLMProvider | None = None, store=None):
        self.inner = inner
        self.store = store                                          # UsageStore opcional: consumo persistente
        self.on_wait = None                                         # aviso (segundos, motivo) mientras el proveedor espera
        self.calls = self.input_tokens = self.output_tokens = 0     # consumo de la sesión

    def generate(self, system, messages, tools, image_png=None) -> LLMResponse:
        inner = self.inner                                          # una sola lectura: el cambio puede ocurrir en otro hilo
        if inner is None:
            raise NoLLM("sin clave de API configurada")
        if hasattr(inner, "on_wait"):
            inner.on_wait = self.on_wait
        r = inner.generate(system, messages, tools, image_png)
        self.calls += 1
        self.input_tokens += r.input_tokens
        self.output_tokens += r.output_tokens
        if self.store is not None:
            self.store.add(r.input_tokens, r.output_tokens)
        return r

    def usage(self) -> dict:
        u = {"calls": self.calls, "input": self.input_tokens, "output": self.output_tokens}        # de la sesión
        return {**u, **self.store.snapshot()} if self.store is not None else u
