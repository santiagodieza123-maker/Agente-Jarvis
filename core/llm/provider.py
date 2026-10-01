"""Interfaz intercambiable del LLM. Las implementaciones concretas (Gemini, etc.) van en módulos aparte."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, system: str, messages: list[dict], tools: list[dict],
                 image_png: bytes | None = None) -> LLMResponse:
        """Una llamada de planificación/decisión. `messages` con contenido observado marcado como no confiable."""
