"""Capturas de pantalla y Set-of-Marks: sobre la captura se dibujan los elementos con su número, de modo que el modelo
puede decir «el 7» en lugar de dar coordenadas. El HUD recibe la captura limpia y dibuja él mismo las cajas (interactivas)."""
from __future__ import annotations

import base64
import io

from perception.model import Snapshot

MAX_WIDTH = 1280
PALETTE = {"button": "#ff9f1a", "edit": "#35e08a", "checkbox": "#c58aff", "radiobutton": "#c58aff", "combobox": "#2fb8ff",
           "hyperlink": "#2fb8ff", "menuitem": "#ffd23f", "tabitem": "#ffd23f", "listitem": "#ff6b9d"}


def capture(rect: tuple[int, int, int, int] | None = None) -> tuple[bytes, tuple[int, int]]:
    """PNG del rectángulo (o del escritorio virtual) y su origen. Requiere `mss`."""
    import mss
    from PIL import Image
    factory = getattr(mss, "MSS", None) or mss.mss               # mss 10: MSS(); versiones anteriores: mss()
    with factory() as sct:
        mon = sct.monitors[0] if rect is None else {"left": rect[0], "top": rect[1], "width": max(1, rect[2] - rect[0]), "height": max(1, rect[3] - rect[1])}
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), (mon["left"], mon["top"])


def _scaled(img_w: int) -> float:
    return min(1.0, MAX_WIDTH / img_w) if img_w else 1.0


def annotate(png: bytes, snap: Snapshot, origin: tuple[int, int] = (0, 0), highlight: int | None = None) -> bytes:
    """Imagen para el modelo: elementos interactivos con caja y número. Reduce a un ancho máximo para limitar tokens."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.open(io.BytesIO(png)).convert("RGB")
    s = _scaled(img.width)
    if s < 1.0:
        img = img.resize((round(img.width * s), round(img.height * s)))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=13)
    except TypeError:                                   # Pillow antiguo
        font = ImageFont.load_default()
    for e in snap.elements:
        if not e.interactive and e.id != highlight:
            continue
        l, t, r, b = ((e.rect[0] - origin[0]) * s, (e.rect[1] - origin[1]) * s, (e.rect[2] - origin[0]) * s, (e.rect[3] - origin[1]) * s)
        if r <= 0 or b <= 0 or l >= img.width or t >= img.height:
            continue
        color = "#ff2d55" if e.id == highlight else PALETTE.get(e.role, "#ffffff")
        d.rectangle([l, t, r, b], outline=color, width=2)
        label = str(e.id)
        tw = d.textlength(label, font=font) + 6
        d.rectangle([l, max(0, t - 15), l + tw, max(15, t)], fill=color)
        d.text((l + 3, max(0, t - 15)), label, fill="black", font=font)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def hud_frame(png: bytes, snap: Snapshot, origin: tuple[int, int] = (0, 0), highlight: int | None = None,
              action: str = "", max_width: int = 960) -> dict:
    """Carga útil del evento `perception.frame`: JPEG reducido + rectángulos en coordenadas de esa imagen."""
    from PIL import Image
    img = Image.open(io.BytesIO(png)).convert("RGB")
    s = min(1.0, max_width / img.width) if img.width else 1.0
    if s < 1.0:
        img = img.resize((round(img.width * s), round(img.height * s)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=70)
    els = [{"id": e.id, "name": e.name[:60], "role": e.role, "interactive": e.interactive, "enabled": e.enabled,
            "rect": [round((e.rect[0] - origin[0]) * s), round((e.rect[1] - origin[1]) * s),
                     round((e.rect[2] - origin[0]) * s), round((e.rect[3] - origin[1]) * s)]}
           for e in snap.elements[:200]]
    return {"image": base64.b64encode(buf.getvalue()).decode(), "width": img.width, "height": img.height,
            "title": snap.window.title[:120], "process": snap.window.process, "seq": snap.seq,
            "elements": els, "highlight": highlight, "action": action[:160]}
