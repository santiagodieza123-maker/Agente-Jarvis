"""Detección visual de elementos con OmniParser v2 (Microsoft): un YOLO localiza botones/iconos en una captura y Florence-2
describe cada uno. Sirve donde UI Automation no ve nada (juegos, apps de dibujo, algunas Electron). Corre en local, con GPU
NVIDIA si hay CUDA. Los pesos (~1 GB, microsoft/OmniParser-v2.0) se descargan a <JARVIS_HOME>/models/omniparser la primera vez.
Licencias de los pesos: icon_detect AGPL-3.0, icon_caption MIT."""
from __future__ import annotations

import importlib.util
import io
import threading
from dataclasses import dataclass
from pathlib import Path

REPO = "microsoft/OmniParser-v2.0"
BOX_CONF, IOU = 0.05, 0.1
MAX_BOXES = 80


@dataclass
class VisualElement:
    id: int
    label: str
    rect: tuple[int, int, int, int]          # relativo a la captura
    conf: float

    @property
    def center(self) -> tuple[int, int]:
        l, t, r, b = self.rect
        return (l + r) // 2, (t + b) // 2


def available() -> bool:
    return all(importlib.util.find_spec(m) is not None for m in ("ultralytics", "transformers", "torch", "huggingface_hub"))


def _overlap(a, b) -> float:
    """Fracción del menor de los dos rectángulos cubierta por la intersección."""
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / small if small > 0 else 0.0


def dedupe(boxes: list[tuple[tuple[int, int, int, int], float]], thr: float = 0.8) -> list[tuple[tuple[int, int, int, int], float]]:
    """Quita cajas casi contenidas en otra de más confianza."""
    keep: list = []
    for rect, conf in sorted(boxes, key=lambda x: -x[1]):
        if all(_overlap(rect, k[0]) < thr for k in keep):
            keep.append((rect, conf))
    return keep


class OmniParser:
    def __init__(self, weights_dir: Path):
        self.dir = Path(weights_dir)
        self._lock = threading.Lock()
        self._yolo = self._cap = self._proc = None
        self.device = "cpu"

    def _download(self) -> None:
        if (self.dir / "icon_detect" / "model.pt").exists() and (self.dir / "icon_caption" / "model.safetensors").exists():
            return
        from huggingface_hub import snapshot_download
        snapshot_download(REPO, local_dir=str(self.dir), allow_patterns=["icon_detect/*", "icon_caption/*"])

    def _load(self) -> None:
        with self._lock:
            if self._yolo is not None:
                return
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
            from ultralytics import YOLO
            self._download()
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if self.device == "cuda" else torch.float32
            self._yolo = YOLO(str(self.dir / "icon_detect" / "model.pt"))
            self._proc = AutoProcessor.from_pretrained("microsoft/Florence-2-base", trust_remote_code=True)
            self._cap = AutoModelForCausalLM.from_pretrained(str(self.dir / "icon_caption"), torch_dtype=dtype,
                                                             trust_remote_code=True).to(self.device).eval()

    def _captions(self, img, rects: list, batch: int = 32) -> list[str]:
        import torch
        crops = [img.crop(r).convert("RGB").resize((64, 64)) for r in rects]
        out: list[str] = []
        dtype = next(self._cap.parameters()).dtype
        for i in range(0, len(crops), batch):
            chunk = crops[i:i + batch]
            inp = self._proc(images=chunk, text=["<CAPTION>"] * len(chunk), return_tensors="pt").to(self.device)
            with torch.inference_mode():
                ids = self._cap.generate(input_ids=inp["input_ids"], pixel_values=inp["pixel_values"].to(dtype),
                                         max_new_tokens=20, num_beams=1, do_sample=False)
            out += [t.strip() for t in self._proc.batch_decode(ids, skip_special_tokens=True)]
        return out

    def parse(self, png: bytes, captions: bool = True) -> list[VisualElement]:
        from PIL import Image
        self._load()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        res = self._yolo.predict(img, conf=BOX_CONF, iou=IOU, verbose=False, device=0 if self.device == "cuda" else "cpu")[0]
        boxes = [(tuple(int(v) for v in b.xyxy[0].tolist()), float(b.conf[0])) for b in res.boxes]
        boxes = [(r, c) for r, c in boxes if r[2] - r[0] >= 4 and r[3] - r[1] >= 4]
        boxes = sorted(dedupe(boxes)[:MAX_BOXES], key=lambda x: (x[0][1] // 20, x[0][0]))      # orden de lectura
        labels = self._captions(img, [r for r, _ in boxes]) if captions and boxes else [""] * len(boxes)
        return [VisualElement(i + 1, lab[:80], r, round(c, 2)) for i, ((r, c), lab) in enumerate(zip(boxes, labels))]
