"""Backend de GUI en memoria para probar GuiTools sin Windows."""
import io
from dataclasses import replace

from perception.backend import GuiBackend, GuiError
from perception.model import Element, Snapshot, WindowInfo


class FakeBackend(GuiBackend):
    def __init__(self):
        self.wins: dict[int, dict] = {}
        self.fg: int | None = None
        self.seq = 0
        self.snaps: dict[int, tuple[int, list[Element]]] = {}
        self.log: list[tuple] = []
        self.on_activate = lambda win, el: None
        self.truncate_typing: int | None = None

    def add_window(self, handle, title, process="app.exe", elements=(), rect=(0, 0, 400, 300), foreground=False):
        self.wins[handle] = {"info": WindowInfo(handle, title, process, handle, rect, False), "els": [replace(e) for e in elements]}
        if foreground:
            self.fg = handle

    def _info(self, h):
        return replace(self.wins[h]["info"], foreground=(h == self.fg))

    def windows(self):
        return [self._info(h) for h in self.wins]

    def foreground(self):
        return self._info(self.fg) if self.fg in self.wins else None

    def observe(self, handle, max_elements):
        if handle not in self.wins:
            raise GuiError("ventana inexistente")
        self.seq += 1
        live = self.wins[handle]["els"][:max_elements]
        els = [replace(e, id=i + 1) for i, e in enumerate(live)]
        self.snaps[self.seq] = (handle, [(i + 1, live[i]) for i in range(len(live))])
        return Snapshot(self.seq, self._info(handle), els, truncated=len(self.wins[handle]["els"]) > max_elements)

    def _live(self, seq, element_id):
        if seq not in self.snaps:
            raise GuiError("observación obsoleta")
        handle, pairs = self.snaps[seq]
        for i, e in pairs:
            if i == element_id:
                if e not in self.wins[handle]["els"]:
                    raise GuiError("el elemento ya no existe")
                return handle, e
        raise GuiError("elemento desconocido")

    def activate(self, seq, element_id):
        handle, e = self._live(seq, element_id)
        self.log.append(("activate", e.name))
        self.on_activate(self.wins[handle], e)
        return "invoke"

    def set_value(self, seq, element_id, text):
        _, e = self._live(seq, element_id)
        e.value = text[: self.truncate_typing] if self.truncate_typing is not None else text
        self.log.append(("set_value", e.name, text))
        return "valor"

    def read_value(self, seq, element_id):
        return self._live(seq, element_id)[1].value

    def focus_window(self, handle):
        self.fg = handle
        self.log.append(("focus", handle))

    def screenshot(self, rect):
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (400, 300), "white").save(b, "PNG")
        return b.getvalue()

    def press(self, combo):
        self.log.append(("press", combo))

    def type_text(self, text):
        self.log.append(("type_text", text))

    def click_xy(self, x, y):
        self.log.append(("click_xy", x, y))
