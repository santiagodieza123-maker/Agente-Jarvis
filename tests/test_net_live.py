"""Pruebas con internet real (túnel CONNECT con TLS real a través del proxy de salida). Solo con JARVIS_NET_TESTS=1 (CI)."""
import asyncio
import os

import pytest

pytest.importorskip("playwright")
from core.tools_web import BlockedURL, WebTools  # noqa: E402

pytestmark = pytest.mark.skipif(os.environ.get("JARVIS_NET_TESTS") != "1", reason="requiere internet directo (JARVIS_NET_TESTS=1)")


def test_https_site_works_through_the_egress_proxy_and_internal_is_blocked(tmp_path):
    async def go():
        w = WebTools(tmp_path / "p")
        try:
            snap = await w.open("https://example.com/")
            assert "Example Domain" in snap
            for bad in ("http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:8765/", "http://localhost/"):
                with pytest.raises(BlockedURL):
                    await w.open(bad)
        finally:
            await w.close()
    asyncio.run(go())
