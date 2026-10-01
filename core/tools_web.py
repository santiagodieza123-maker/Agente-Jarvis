"""Navegador headless-first (Playwright) con perfil dedicado y bloqueo de destinos internos (anti-SSRF)."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

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


class WebTools:
    def __init__(self, profile_dir: str | Path, headless: bool = True,
                 allowed_private: frozenset[str] = frozenset()):
        """`allowed_private`: 'host:puerto' que se permiten aunque sean privados (solo para pruebas)."""
        self.profile_dir, self.headless, self.allowed_private = Path(profile_dir), headless, allowed_private
        self._pw = self._ctx = self._page = None
        self._lock = asyncio.Lock()
        self._dns: dict[str, bool] = {}
        self._redirect: str | None = None

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
        if host not in self._dns:
            try:
                infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
                self._dns[host] = all(ipaddress.ip_address(i[4][0]).is_global for i in infos)
            except (socket.gaierror, ValueError):
                self._dns[host] = False
        if not self._dns[host]:
            raise BlockedURL(f"destino interno o irresoluble bloqueado: {host}")

    async def _route(self, route) -> None:
        """Cada petición y cada salto de redirección se valida antes de salir.
        Tras entregar una respuesta, el navegador sigue las redirecciones SIN volver a interceptarlas, así que:
          - navegación del frame principal: se aborta y `_goto` vuelve a navegar al destino (pasa de nuevo por aquí);
          - subrecursos e iframes: se siguen aquí dentro, validando cada `Location`, y se entrega la respuesta final.
        Limitación conocida: DNS rebinding entre la comprobación y la conexión (TOCTOU) no queda cubierto."""
        req = route.request
        url = req.url
        try:
            await self.check_url(url)
        except BlockedURL:
            return await route.abort("blockedbyclient")
        if urlsplit(url).scheme not in ("http", "https"):
            return await route.continue_()
        try:
            main_nav = req.is_navigation_request() and req.frame.parent_frame is None
        except Exception:
            main_nav = False
        try:
            resp = await route.fetch(max_redirects=0)
            for _ in range(10):
                loc = resp.headers.get("location")
                if not (300 <= resp.status < 400 and loc):
                    return await route.fulfill(response=resp)
                url = urljoin(url, loc)
                await self.check_url(url)              # BlockedURL si el siguiente salto es interno
                if main_nav:
                    self._redirect = url
                    return await route.abort("aborted")
                resp = await route.fetch(url=url, max_redirects=0)
            return await route.abort("failed")          # demasiadas redirecciones
        except BlockedURL:
            return await route.abort("blockedbyclient")
        except Exception:
            return await route.abort("failed")

    async def _goto(self, url: str) -> None:
        p = await self._page_()
        for _ in range(10):
            self._redirect = None
            try:
                await p.goto(url, timeout=20_000, wait_until="domcontentloaded")
            except Exception:
                if self._redirect is None:
                    raise
            if self._redirect is None:
                return
            url = self._redirect
        raise BlockedURL("demasiadas redirecciones")

    async def _settle(self) -> None:
        """Completa una redirección de navegación pendiente tras un clic/envío."""
        await asyncio.sleep(0.3)
        if self._redirect:
            await self._goto(self._redirect)

    # --- ciclo de vida ---
    async def _page_(self):
        async with self._lock:
            if self._page is None:
                from playwright.async_api import async_playwright
                self._pw = await async_playwright().start()
                self._ctx = await self._pw.chromium.launch_persistent_context(
                    str(self.profile_dir), headless=self.headless, accept_downloads=False)
                await self._ctx.route("**/*", self._route)
                self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
        return self._page

    async def close(self) -> None:
        if self._ctx:
            await self._ctx.close()
        if self._pw:
            await self._pw.stop()
        self._pw = self._ctx = self._page = None

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
        self._redirect = None
        await el.click(timeout=5000)
        await self._settle()
        return await self._snapshot()

    async def type(self, target: str, text: str, submit: bool = False) -> str:
        el = await self._find(target)
        await el.fill(text, timeout=5000)
        if submit:
            self._redirect = None
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
