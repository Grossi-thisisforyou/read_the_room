"""The real network stack on localhost: WebSocket, HTTP fallback, UDP, JPEG stream."""
import asyncio
import json
import socket

import aiohttp

from showengine import config, protocol as P
from showengine.engine import Engine
from showengine.hub import Hub


def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_hub_end_to_end():
    asyncio.run(_scenario())


async def _scenario():
    port, udp, tcp = free_port(), free_port(socket.SOCK_DGRAM), free_port()
    cfg = config.load(None, {"network": {"host": "127.0.0.1", "port": port, "udp_port": udp, "tcp_port": tcp},
                             "presence": {"on_hold": 0.1}, "visit": {"approach_time": 0.3}})
    eng = Engine(cfg)
    hub = Hub(eng, cfg)
    await hub.start()
    base = f"http://127.0.0.1:{port}"
    try:
        async with aiohttp.ClientSession() as s:
            prof = await s.ws_connect(f"{base}/ws")
            await prof.send_str(P.encode(P.make(P.HELLO, {"role": "profiler"})))
            first = P.decode((await prof.receive()).data)
            assert first["type"] == P.STATE and first["data"]["phase"] == "idle"

            phone = await s.ws_connect(f"{base}/ws")
            await phone.send_str(P.encode(P.make(P.HELLO, {"role": "phone", "device": "n900"})))
            await phone.receive()
            for _ in range(15):
                await phone.send_str(P.encode(P.make(P.SENSOR, {"kind": "phone", "motion": 0.8})))
                await asyncio.sleep(0.05)
            await phone.send_str("not json at all")        # ignored, connection stays up

            seen = set()
            for _ in range(80):
                m = P.decode((await asyncio.wait_for(prof.receive(), 2)).data)
                seen.add(m["type"])
                if m["type"] == P.STATE:
                    seen.add("phase:" + m["data"]["phase"])
                if {"sensor", "visit", "phase:approach"} <= seen:
                    break
            assert {"sensor", "visit", "phase:approach"} <= seen, seen

            # a phone may not send control
            await phone.send_str(P.encode(P.make(P.CONTROL, {"cmd": "blackout"})))
            await asyncio.sleep(0.05)
            assert not eng.blackout

            # HTTP fallback, a batch of envelopes
            r = await s.post(f"{base}/api/sensor", data=json.dumps([P.make(P.SENSOR, {"motion": .5})] * 3))
            assert (await r.json())["accepted"] == 3
            n = eng.stats["sensor"]

            # UDP fast lane with sequence numbers (one lost on purpose)
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for seq in (1, 2, 4):
                sock.sendto(P.encode(P.make(P.SENSOR, {"motion": .5, "seq": seq})).encode(), ("127.0.0.1", udp))
            sock.close()
            await asyncio.sleep(0.1)
            assert eng.stats["sensor"] == n + 3 and hub.udp_seq["lost"] == 1

            # raw JPEG stream: a real 8x8 JPEG made by pygame, sent twice back-to-back
            import io, pygame
            surf = pygame.Surface((8, 8))
            surf.fill((200, 10, 10))
            buf = io.BytesIO()
            pygame.image.save(surf, buf, "x.jpg")
            _, w = await asyncio.open_connection("127.0.0.1", tcp)
            w.write(buf.getvalue())
            await w.drain()
            await asyncio.sleep(0.15)
            w.write(buf.getvalue())
            await w.drain()
            await asyncio.sleep(0.1)
            w.close()
            assert eng.stats["frame"] >= 1

            st = await (await s.get(f"{base}/status")).json()
            assert st["clients"] == {"profiler": 1, "phone": 1} and st["phase"] in ("approach", "profiling")
            assert (await s.get(f"{base}/")).status == 200

            ctl = await s.ws_connect(f"{base}/ws")
            await ctl.send_str(P.encode(P.make(P.HELLO, {"role": "control"})))
            await ctl.send_str(P.encode(P.make(P.CONTROL, {"cmd": "wipe"})))
            await asyncio.sleep(0.1)
            assert eng.machine.phase == "wipe"
            for ws in (prof, phone, ctl):
                await ws.close()
    finally:
        await hub.stop()
