import asyncio

import pytest

from core.egress_proxy import BLOCKED_HEADER, EgressProxy, is_public, split_hostport

PUBLIC = "93.184.216.34"


class Upstream:
    """Servidor local que hace de 'internet': registra lo recibido y responde."""
    def __init__(self):
        self.received, self.server, self.port = [], None, 0

    async def start(self):
        async def handle(r, w):
            data = await r.read(4096)
            self.received.append(data)
            if data.startswith(b"GET") or data.startswith(b"POST"):
                w.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            else:
                w.write(b"eco:" + data)
            await w.drain()
            w.close()
        self.server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()


def make_proxy(up, resolver_map=None, **kw):
    dialed = []

    async def resolver(host, port):
        v = (resolver_map or {}).get(host)
        if v is None:
            raise OSError("NXDOMAIN")
        return v() if callable(v) else v

    async def opener(ip, port):
        dialed.append(ip)
        return await asyncio.open_connection("127.0.0.1", up.port)       # todo 'internet' es el servidor local

    p = EgressProxy(resolver=resolver, opener=opener, **kw)
    return p, dialed


async def raw(port, payload: bytes, read=65536, wait=1.0) -> bytes:
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(payload)
    await w.drain()
    try:
        return await asyncio.wait_for(r.read(read), wait)
    except asyncio.TimeoutError:
        return b""
    finally:
        w.close()


def run(coro):
    return asyncio.run(coro)


def test_is_public_and_hostport():
    for ip in ("93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"):
        assert is_public(ip)
    for ip in ("127.0.0.1", "10.1.2.3", "192.168.0.1", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "::ffff:127.0.0.1",
               "::ffff:10.0.0.1", "224.0.0.1", "100.64.0.1", "fc00::1"):
        assert not is_public(ip), ip
    assert split_hostport("ex.com:8443", 443) == ("ex.com", 8443) and split_hostport("ex.com", 443) == ("ex.com", 443)
    assert split_hostport("[::1]:80", 443) == ("::1", 80) and split_hostport("[::1]", 443) == ("::1", 443)
    for bad in ("", ":80", "a:b", "a:0", "a:70000"):
        with pytest.raises(ValueError):
            split_hostport(bad, 443)


def test_connect_tunnel_to_public_host_dials_the_validated_ip():
    async def go():
        up = Upstream(); await up.start()
        p, dialed = make_proxy(up, {"pub.example": [PUBLIC]})
        port = await p.start()
        out = await raw(port, b"CONNECT pub.example:443 HTTP/1.1\r\nHost: pub.example:443\r\n\r\n", wait=0.5)
        assert out.startswith(b"HTTP/1.1 200")
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"CONNECT pub.example:443 HTTP/1.1\r\n\r\n"); await w.drain()
        assert (await r.readuntil(b"\r\n\r\n")).startswith(b"HTTP/1.1 200")
        w.write(b"hola"); await w.drain()
        assert await asyncio.wait_for(r.read(100), 2) == b"eco:hola"
        w.close()
        assert set(dialed) == {PUBLIC}
        await p.stop(); await up.stop()
    run(go())


@pytest.mark.parametrize("target", ["127.0.0.1:80", "169.254.169.254:80", "10.0.0.5:443", "[::1]:443", "[::ffff:127.0.0.1]:80", "localhost:80", "interno.example:80", "mixto.example:80"])
def test_connect_to_internal_destinations_is_blocked_and_never_dialed(target):
    async def go():
        up = Upstream(); await up.start()
        blocks = []
        p, dialed = make_proxy(up, {"localhost": ["127.0.0.1", "::1"], "interno.example": ["10.1.1.1"], "mixto.example": [PUBLIC, "192.168.1.1"]},
                               on_block=lambda h, why: blocks.append((h, why)))
        port = await p.start()
        out = await raw(port, f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
        assert out.startswith(b"HTTP/1.1 403") and BLOCKED_HEADER.encode() in out
        assert dialed == [] and up.received == [] and len(blocks) == 1
        await p.stop(); await up.stop()
    run(go())


def test_dns_rebinding_cannot_reach_internal_address():
    """El nombre resuelve a una IP pública la primera vez y a 127.0.0.1 después: el proxy resuelve UNA vez por conexión
    y conecta a lo validado, así que nunca se llega a la dirección interna."""
    async def go():
        up = Upstream(); await up.start()
        answers = iter([[PUBLIC], ["127.0.0.1"], ["127.0.0.1"]])
        p, dialed = make_proxy(up, {"rebind.example": lambda: next(answers)})
        port = await p.start()
        o1 = await raw(port, b"CONNECT rebind.example:80 HTTP/1.1\r\n\r\n", wait=0.3)
        o2 = await raw(port, b"CONNECT rebind.example:80 HTTP/1.1\r\n\r\n")
        assert o1.startswith(b"HTTP/1.1 200") and o2.startswith(b"HTTP/1.1 403")
        assert dialed == [PUBLIC]
        await p.stop(); await up.stop()
    run(go())


def test_plain_http_is_rewritten_to_origin_form_and_forced_to_close():
    async def go():
        up = Upstream(); await up.start()
        p, dialed = make_proxy(up, {"pub.example": [PUBLIC]})
        port = await p.start()
        req = (b"GET http://pub.example/a/b?x=1 HTTP/1.1\r\nHost: pub.example\r\nProxy-Connection: keep-alive\r\n"
               b"Proxy-Authorization: Basic eHg=\r\nConnection: keep-alive\r\nAccept: */*\r\n\r\n")
        out = await raw(port, req)
        assert out.endswith(b"ok") and out.startswith(b"HTTP/1.1 200")
        got = up.received[0].decode().lower()
        assert got.startswith("get /a/b?x=1 http/1.1") and "host: pub.example" in got and "accept: */*" in got
        assert "proxy-" not in got and "keep-alive" not in got and "connection: close" in got
        assert dialed == [PUBLIC]
        await p.stop(); await up.stop()
    run(go())


def test_plain_http_to_internal_gets_403_page_not_a_connection():
    async def go():
        up = Upstream(); await up.start()
        p, dialed = make_proxy(up, {"nas.local": ["192.168.1.10"]})
        port = await p.start()
        for t in (b"http://127.0.0.1:8765/", b"http://nas.local/admin", b"http://169.254.169.254/latest/meta-data/", b"http://[::1]/"):
            out = await raw(port, b"GET " + t + b" HTTP/1.1\r\nHost: x\r\n\r\n")
            assert out.startswith(b"HTTP/1.1 403"), t
        assert dialed == [] and up.received == []
        await p.stop(); await up.stop()
    run(go())


def test_malformed_requests_get_400_or_close():
    async def go():
        up = Upstream(); await up.start()
        p, dialed = make_proxy(up, {"pub.example": [PUBLIC]})
        port = await p.start()
        for bad in (b"GET /solo-ruta HTTP/1.1\r\n\r\n", b"GET https://pub.example/ HTTP/1.1\r\n\r\n", b"BASURA\r\n\r\n",
                    b"CONNECT :80 HTTP/1.1\r\n\r\n", b"CONNECT a:b HTTP/1.1\r\n\r\n"):
            assert (await raw(port, bad)).startswith(b"HTTP/1.1 400"), bad
        assert (await raw(port, b"GET / HTTP/1.1\r\nHost: x\r\n", wait=0.3)) == b""     # cabecera sin terminar: se queda esperando y se cierra al expirar
        assert dialed == []
        await p.stop(); await up.stop()
    run(go())


def test_allowed_private_is_honoured_only_for_the_exact_host_and_port():
    async def go():
        up = Upstream(); await up.start()
        p, dialed = make_proxy(up, {"localhost": ["127.0.0.1"]}, allowed_private=frozenset({"localhost:8080"}))
        port = await p.start()
        assert (await raw(port, b"GET http://localhost:8080/ HTTP/1.1\r\nHost: x\r\n\r\n")).startswith(b"HTTP/1.1 200")
        assert (await raw(port, b"GET http://localhost:8081/ HTTP/1.1\r\nHost: x\r\n\r\n")).startswith(b"HTTP/1.1 403")
        await p.stop(); await up.stop()
    run(go())


def test_websocket_upgrade_headers_are_preserved():
    async def go():
        up = Upstream(); await up.start()
        p, _ = make_proxy(up, {"pub.example": [PUBLIC]})
        port = await p.start()
        await raw(port, b"GET http://pub.example/ws HTTP/1.1\r\nHost: pub.example\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n")
        got = up.received[0].decode().lower()
        assert "upgrade: websocket" in got and "connection: upgrade" in got and "connection: close" not in got
        await p.stop(); await up.stop()
    run(go())


def test_unresolvable_host_is_blocked():
    async def go():
        up = Upstream(); await up.start()
        p, dialed = make_proxy(up, {})
        port = await p.start()
        assert (await raw(port, b"CONNECT nope.example:443 HTTP/1.1\r\n\r\n")).startswith(b"HTTP/1.1 403")
        await p.stop(); await up.stop()
    run(go())


def test_stop_closes_open_tunnels():
    async def go():
        up = Upstream(); await up.start()
        p, _ = make_proxy(up, {"pub.example": [PUBLIC]})
        port = await p.start()
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"CONNECT pub.example:443 HTTP/1.1\r\n\r\n"); await w.drain()
        await r.readuntil(b"\r\n\r\n")
        await p.stop()
        assert await asyncio.wait_for(r.read(10), 2) == b""        # el túnel se cerró
        await up.stop()
    run(go())
