"""A fake N900 for testing anywhere: visitors walk in, linger, touch, leave.

    python3 -m showengine.sim                     # talk to an engine on localhost
    python3 -m showengine.sim --url ws://192.168.1.10:8765/ws

The engine's own `--simulate` flag runs the same script inside the engine, so a
laptop with no phone and no network shows the whole cycle.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import random
import time
from typing import AsyncIterator

from . import protocol as P


async def visitors(seed: int | None = None, gap: tuple[float, float] = (6, 15),
                   stay: tuple[float, float] = (35, 90), hz: float = 10) -> AsyncIterator[dict]:
    """Endless sensor messages: empty room, then a visitor with a temperament, then empty."""
    rnd = random.Random(seed)
    dt = 1.0 / hz
    while True:
        for _ in range(int(rnd.uniform(*gap) * hz)):          # empty room
            yield P.make(P.SENSOR, {"kind": "phone", "motion": rnd.uniform(0, 0.04),
                                    "loudness": rnd.uniform(0, 0.05), "light": 0.2,
                                    "proximity": {"near": False}, "held": False})
            await asyncio.sleep(dt)
        energy, nerves, curious = rnd.random(), rnd.random(), rnd.random()
        n = int(rnd.uniform(*stay) * hz)
        for i in range(n):
            t = i * dt
            motion = 0.25 + 0.6 * energy * abs(math.sin(t * (0.3 + energy))) + nerves * rnd.uniform(0, 0.3)
            d = {"kind": "phone", "motion": min(1, motion), "light": 0.25,
                 "audio": {"level": min(1, 0.1 + 0.5 * energy * rnd.random()), "voiced": rnd.random() < energy * 0.3},
                 "tilt": {"alpha": 0, "beta": 20 * math.sin(t * nerves * 3), "gamma": 10 * math.cos(t)},
                 "proximity": {"near": rnd.random() < 0.05}, "held": True,   # handheld: the visitor picks the phone up
                 "shake": min(1.0, nerves * rnd.random() * 0.5)}
            yield P.make(P.SENSOR, d)
            if rnd.random() < curious * 0.04:
                yield P.make(P.SENSOR, {"kind": "touch", "x": rnd.random(), "y": rnd.random(), "down": True})
            await asyncio.sleep(dt)


async def run_client(url: str, seed: int | None) -> None:
    import aiohttp
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(url) as ws:
            await ws.send_str(P.encode(P.make(P.HELLO, {"role": "phone", "device": "sim"})))

            async def show():
                async for m in ws:
                    msg = P.decode(m.data)
                    if msg["type"] == P.STATE:
                        d = msg["data"]
                        print(f"\r{d['phase']:>9} {d['phase_t']:5.1f}s  {d['scene']:>10}  int {d['intensity']:.2f}  "
                              f"{d['tempo']:5.1f}bpm  hook {d['hook'] or '-':>8}   ", end="", flush=True)
                    elif msg["type"] in (P.PHONE, P.WIPE):
                        print(f"\n[{msg['type']}] {msg['data']}")

            reader = asyncio.ensure_future(show())
            try:
                async for msg in visitors(seed):
                    msg["ts"] = time.time()
                    await ws.send_str(P.encode(msg))
            finally:
                reader.cancel()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    try:
        asyncio.run(run_client(a.url, a.seed))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
