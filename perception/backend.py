"""Interfaz del backend de GUI: UIABackend (Windows) y FakeBackend (pruebas). Todas las llamadas son síncronas;
el backend decide en qué hilo se ejecutan (UI Automation exige un único hilo con COM inicializado)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from perception.model import Snapshot, WindowInfo


class GuiError(RuntimeError):
    pass


class GuiBackend(ABC):
    @abstractmethod
    def windows(self) -> list[WindowInfo]: ...

    @abstractmethod
    def observe(self, handle: int | None, max_elements: int) -> Snapshot: ...

    @abstractmethod
    def activate(self, seq: int, element_id: int) -> str:
        """Invoca/alterna/selecciona el elemento (patrón UIA) o, si no hay patrón, hace clic en su centro. Devuelve el método usado."""

    @abstractmethod
    def set_value(self, seq: int, element_id: int, text: str) -> str: ...

    @abstractmethod
    def read_value(self, seq: int, element_id: int) -> str | None: ...

    @abstractmethod
    def focus_window(self, handle: int) -> None: ...

    @abstractmethod
    def foreground(self) -> WindowInfo | None: ...

    @abstractmethod
    def screenshot(self, rect: tuple[int, int, int, int] | None) -> bytes:
        """PNG del rectángulo (o del escritorio virtual completo)."""

    @abstractmethod
    def press(self, combo: str) -> None: ...

    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def click_xy(self, x: int, y: int) -> None: ...

    def run(self, fn, *args):
        """Ejecuta fn en el hilo del backend (por defecto, el actual)."""
        return fn(*args)
