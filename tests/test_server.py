import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from core.bus import EventBus, make_event
from core.server import HudServer


def run(coro):
    return asyncio.run(coro)


def test_unknown_event_rejected():
    with pytest.raises(ValueError):
        make_event("nope", {})


def test_event_delivered_with_valid_token():
    async def go():
        bus = EventBus()
        srv = HudServer(bus)
        port = await srv.start()
        try:
            async with connect(f"ws://127.0.0.1:{port}/?token={srv.token}") as ws:
                await asyncio.sleep(0.05)
                bus.publish("state.changed", {"state": "thinking"})
                ev = json.loads(await asyncio.wait_for(ws.recv(), 2))
                assert ev["type"] == "state.changed" and ev["payload"]["state"] == "thinking"
        finally:
            await srv.stop()
    run(go())


@pytest.mark.parametrize("query,headers,status", [
    ("?token=malo", {}, 401),
    ("", {}, 401),
    ("TOKEN", {"Origin": "http://evil.example"}, 403),
])
def test_rejections(query, headers, status):
    async def go():
        srv = HudServer(EventBus())
        port = await srv.start()
        q = f"?token={srv.token}" if query == "TOKEN" else query
        try:
            with pytest.raises(InvalidStatus) as e:
                async with connect(f"ws://127.0.0.1:{port}/{q}", additional_headers=headers):
                    pass
            assert e.value.response.status_code == status
        finally:
            await srv.stop()
    run(go())


def test_slow_subscriber_never_blocks():
    bus = EventBus(maxsize=2)
    q = bus.subscribe()
    for i in range(10):
        bus.publish("state.changed", {"i": i})
    assert q.qsize() == 2


def test_abrupt_disconnect_is_not_a_handler_error(capsys):
    import asyncio
    from websockets.exceptions import ConnectionClosedError
    from core.bus import EventBus
    from core.server import HudServer

    class Ws:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise ConnectionClosedError(None, None)
        async def send(self, _):
            pass

    srv = HudServer(EventBus(), token="t")
    asyncio.run(srv._handler(Ws()))
    assert srv.clients == 0
