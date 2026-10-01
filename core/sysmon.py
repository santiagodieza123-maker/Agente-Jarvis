"""Estado del sistema para el panel SISTEMA: CPU/memoria del núcleo y sus hijos, retardo del bucle de eventos, GPU (nvidia-smi si
existe), latencia del LLM y salud de cada componente. Solo lectura; se muestrea únicamente mientras haya un HUD conectado."""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from collections import deque
from typing import Callable

import psutil


def parse_nvidia(out: str) -> dict | None:
    """Salida de `nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits` (primera GPU)."""
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            try:
                return {"name": parts[0][:40], "util": float(parts[1]), "mem_used": float(parts[2]), "mem_total": float(parts[3])}
            except ValueError:
                continue
    return None


def default_gpu_query() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--query-gpu=name,utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=3)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


class SystemMonitor:
    def __init__(self, components: Callable[[], list[dict]], llm_stats: Callable[[], dict], clients: Callable[[], int] = lambda: 0,
                 gpu_query: Callable[[], str | None] = default_gpu_query, gpu_every: float = 10.0):
        self.components, self.llm_stats, self.clients, self.gpu_query = components, llm_stats, clients, gpu_query
        self.proc = psutil.Process(os.getpid())
        self.started = time.time()
        self._gpu: dict | None = None
        self._gpu_at = 0.0
        self._gpu_every = gpu_every
        self.proc.cpu_percent(None)                      # la primera lectura sirve de referencia
        psutil.cpu_percent(None)
        self._cpu_cache: dict[int, psutil.Process] = {}
        self.lag_ms = 0.0

    async def measure_lag(self, probe: float = 0.05) -> None:
        """Retardo del bucle de eventos: lo que tarda en volver un sleep corto frente a lo pedido."""
        t0 = time.perf_counter()
        await asyncio.sleep(probe)
        self.lag_ms = max(0.0, (time.perf_counter() - t0 - probe) * 1000)

    def _children(self) -> list[dict]:
        out = []
        try:
            kids = self.proc.children(recursive=True)
        except psutil.Error:
            return out
        for c in kids[:20]:
            try:
                c = self._cpu_cache.setdefault(c.pid, c)
                out.append({"pid": c.pid, "name": c.name()[:40], "cpu": round(c.cpu_percent(None), 1), "rss": c.memory_info().rss})
            except psutil.Error:
                continue
        live = {k.pid for k in kids}
        for pid in list(self._cpu_cache):
            if pid not in live:
                del self._cpu_cache[pid]
        return out

    def _gpu_info(self) -> dict | None:
        now = time.time()
        if now - self._gpu_at >= self._gpu_every:
            self._gpu_at = now
            raw = self.gpu_query()
            self._gpu = parse_nvidia(raw) if raw else None
        return self._gpu

    def sample(self) -> dict:
        vm = psutil.virtual_memory()
        try:
            rss, threads = self.proc.memory_info().rss, self.proc.num_threads()
            cpu = self.proc.cpu_percent(None)
        except psutil.Error:
            rss, threads, cpu = 0, 0, 0.0
        return {"ts": time.time(), "uptime": round(time.time() - self.started, 1),
                "cpu": {"process": round(cpu, 1), "system": round(psutil.cpu_percent(None), 1), "cores": psutil.cpu_count() or 0},
                "memory": {"rss": rss, "system_percent": round(vm.percent, 1), "system_total": vm.total},
                "threads": threads, "loop_lag_ms": round(self.lag_ms, 1), "gpu": self._gpu_info(),
                "children": self._children(), "llm": self.llm_stats(), "components": self.components(), "clients": self.clients()}


def llm_stats_from(holder) -> dict:
    lat = list(holder.latencies)
    return {"calls": holder.calls, "errors": holder.errors, "last_ms": round(lat[-1]) if lat else None,
            "avg_ms": round(sum(lat) / len(lat)) if lat else None, "p95_ms": round(sorted(lat)[int(0.95 * (len(lat) - 1))]) if lat else None,
            "ready": holder.inner is not None, "model": getattr(holder.inner, "model", None)}
