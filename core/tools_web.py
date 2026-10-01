"""Navegador headless-first (Playwright) con perfil dedicado y bloqueo de destinos internos (anti-SSRF).
Todo el tráfico del navegador pasa por `EgressProxy`, que valida la IP *en el momento de conectar* (sin ventana de DNS
rebinding) y cubre redirecciones, subrecursos y WebSockets. `check_url` es solo una primera barrera con mensajes claros."""
from __future__ import annotations

import asyncio
import ipaddress
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit

from core.egress_proxy import BLOCKED_HEADER, EgressProxy, default_opener, default_resolver, is_public
from core.orchestrator import Tool
from core.policy import ActionClass

MAX_TEXT = 6000
ELEMENTS_JS = """() => [...document.querySelectorAll('a[href],button,input,textarea,select,[role=button]')]
  .filter(e => e.offsetParent !== null && !(e.type === 'hidden'))
  .slice(0, 40)
  .map(e => `${e.tagName.toLowerCase()}${e.type ? '[' + e.type + ']' : ''}: ` +
       (e.getAttribute('aria-label') || e.innerText || e.placeholder || e.name || e.value || e.title || '').trim().slice(0, 60))"""


class BlockedURL(Exception):
    pass


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class WebTools:
    def __init__(self, profile_dir: str | Path, headless: bool = True,
                 allowed_private: frozenset[str] = frozenset(), resolver=None, opener=None):
        """`allowed_private`: 'host:puerto' que se permiten aunque sean privados (solo para pruebas).
        `resolver` / `opener`: sustituyen al DNS y a la conexión del proxy (pruebas de rebinding)."""
        self._resolver, self._opener = resolver or default_resolver, opener or default_opener
        self.profile_dir, self.headless, self.allowed_private = Path(profile_dir), headless, allowed_private
        self._pw = self._ctx = self._page = None
        self._lock = asyncio.Lock()
        self._proxy: EgressProxy | None = None
        self.blocked_recently = False
        self.blocked: list[str] = []            # destinos rechazados por el proxy (últimos 50)

    # --- política de destinos ---
    async def check_url(self, url: str) -> None:
        u = urlsplit(url)
        if u.scheme in ("data", "about", "blob"):
            return
        if u.scheme not in ("http", "https") or not u.hostname:
            raise BlockedURL(f"esquema no permitido: {u.scheme or '?'}")
        if f"{u.hostname}:{u.port or (443 if u.scheme == 'https' else 80)}" in self.allowed_private:
            return
        host = u.hostname
        try:
            ips = [host] if _is_ip(host) else await self._resolver(host, u.port or (443 if u.scheme == "https" else 80))
            ok = bool(ips) and all(is_public(ip) for ip in ips)
        except (OSError, ValueError):
            ok = False
        if not ok:
            raise BlockedURL(f"destino interno o irresoluble bloqueado: {host}")

    async def _route(self, route) -> None:
        """Primera barrera (esquema y resolución previa). La barrera real es el proxy de salida, que valida cada conexión,
        incluidas las de redirecciones y subrecursos, contra la IP a la que realmente se conecta."""
        try:
            await self.check_url(route.request.url)
        except BlockedURL:
            return await route.abort("blockedbyclient")
        await route.continue_()

    def _on_block(self, host: str, reason: str) -> None:
        self.blocked = (self.blocked + [f"{host}: {reason}"])[-50:]
        self.blocked_recently = True

    async def _goto(self, url: str) -> None:
        p = await self._page_()
        resp = await p.goto(url, timeout=20_000, wait_until="domcontentloaded")
        if resp is not None and resp.headers.get(BLOCKED_HEADER.lower()):
            raise BlockedURL(f"destino interno bloqueado tras redirección o resolución: {(await resp.text())[:120]}")

    async def _settle(self) -> None:
        """Tras un clic/envío, espera a que termine la navegación que haya provocado y comprueba que no fue bloqueada."""
        await asyncio.sleep(0.3)
        p = await self._page_()
        with suppress(Exception):
            await p.wait_for_load_state("domcontentloaded", timeout=5000)
        if self.blocked_recently:
            self.blocked_recently = False
            raise BlockedURL("la navegación fue bloqueada por el proxy de salida (destino interno)")

    # --- ciclo de vida ---
    async def _page_(self):
        async with self._lock:
            if self._page is None:
                from playwright.async_api import async_playwright
                self._proxy = EgressProxy(self.allowed_private, resolver=self._resolver, opener=self._opener, on_block=self._on_block)
                port = await self._proxy.start()
                self._pw = await async_playwright().start()
                self._ctx = await self._pw.chromium.launch_persistent_context(
                    str(self.profile_dir), headless=self.headless, accept_downloads=False,
                    args=[f"--proxy-server=http://127.0.0.1:{port}",
                          "--proxy-bypass-list=<-loopback>",                       # localhost también pasa (y se bloquea) en el proxy
                          "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
                await self._ctx.route("**/*", self._route)
                self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        return self._page

    async def close(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()
        if self._proxy:
            await self._proxy.stop()
        self._pw = self._ctx = self._page = self._proxy = None

    # --- herramientas ---
    async def _snapshot(self) -> str:
        p = await self._page_()
        text = (await p.inner_text("body", timeout=5000))[:MAX_TEXT] if p.url != "about:blank" else ""
        els = await p.evaluate(ELEMENTS_JS) if p.url != "about:blank" else []
        return f"URL: {p.url}\nTÍTULO: {await p.title()}\nTEXTO:\n{text}\nELEMENTOS:\n" + "\n".join(els)

    async def open(self, url: str) -> str:
        await self.check_url(url)
        await self._goto(url)
        return await self._snapshot()

    async def read(self) -> str:
        return await self._snapshot()

    async def _find(self, target: str):
        p = await self._page_()
        for loc in (p.get_by_role("button", name=target), p.get_by_role("link", name=target),
                    p.get_by_label(target), p.get_by_placeholder(target), p.get_by_text(target)):
            if await loc.count():
                return loc.first
        raise LookupError(f"no encuentro un elemento con '{target}'")

    async def click(self, target: str) -> str:
        el = await self._find(target)
        self.blocked_recently = False
        await el.click(timeout=5000)
        await self._settle()
        return await self._snapshot()

    async def type(self, target: str, text: str, submit: bool = False) -> str:
        el = await self._find(target)
        await el.fill(text, timeout=5000)
        if submit:
            self.blocked_recently = False
            await el.press("Enter")
            await self._settle()
        return await self._snapshot()

    def tools(self) -> list[Tool]:
        def params(**f):
            return {"type": "object", "properties": {k: {"type": t} for k, t in f.items()},
                    "required": [k for k in f if k != "submit"]}
        R, W = ActionClass.READ, ActionClass.WRITE_REVERSIBLE
        return [
            Tool("web.open", R, self.open, "Abre una URL http(s) pública y devuelve texto y elementos", True, parameters=params(url="string")),
            Tool("web.read", R, self.read, "Devuelve el texto y los elementos de la página actual", True),
            Tool("web.click", W, self.click, "Hace clic en un botón/enlace por su texto visible", True, parameters=params(target="string")),
            Tool("web.type", W, self.type, "Escribe en un campo (por etiqueta/placeholder); submit=true pulsa Enter", True,
                 parameters=params(target="string", text="string", submit="boolean")),
        ]
