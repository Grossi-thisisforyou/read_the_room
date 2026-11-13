"""The network side: one aiohttp server on port 8765, plus UDP 8766 and TCP 8767.

    ws://<pi>:8765/ws        WebSocket, everyone (first message: hello with a role)
    POST /api/sensor         one envelope or a JSON array of them (N900 fallback)
    POST /api/frame          one frame envelope
    GET  /status             JSON health
    GET  /phone/...          static files from infinite_jest/phone/
    GET  /                   a tiny control page for Baby's laptop
    UDP 8766                 one sensor envelope per datagram
    TCP 8767                 raw back-to-back JPEGs from the N900 camera (gstreamer)

Nothing here stores anything: messages go straight into the engine.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from . import protocol as P
from .engine import Engine
from .plugins import REPO_ROOT

log = logging.getLogger("showengine.hub")

PHONE_DIR = REPO_ROOT / "infinite_jest" / "phone"
CONTROL_PAGE = Path(__file__).with_name("control.html")
MAX_JPEG_BUFFER = 1024 * 1024


class Hub:
    def __init__(self, engine: Engine, cfg: dict):
        self.engine = engine
        self.cfg = cfg
        self.clients: dict[web.WebSocketResponse, str] = {}
        self.started = time.time()
        self.fps = 0.0
        self._runner: web.AppRunner | None = None
        self._udp = None
        self._tcp: asyncio.base_events.Server | None = None
        self.udp_seq: dict[str, int] = {"received": 0, "lost": 0}
        self._last_seq: int | None = None
        engine.emit = self.emit

    # ----------------------------------------------------------- outgoing
    def emit(self, msg: dict, roles: set[str] | None) -> None:
        if not self.clients:
            return
        text = P.encode(msg)
        for ws, role in list(self.clients.items()):
            if roles is None or role in roles:
                if ws.closed:
                    self.clients.pop(ws, None)
                    continue
                asyncio.ensure_future(self._send(ws, text))

    async def _send(self, ws: web.WebSocketResponse, text: str) -> None:
        try:
            await ws.send_str(text)
        except Exception:
            self.clients.pop(ws, None)

    # ----------------------------------------------------------- http + ws
    def app(self) -> web.Application:
        app = web.Application(client_max_size=P.MAX_MESSAGE_BYTES)
        app.router.add_get("/ws", self.ws_handler)
        app.router.add_post("/api/sensor", self.post_sensor)
        app.router.add_post("/api/frame", self.post_frame)
        app.router.add_get("/status", self.get_status)
        app.router.add_get("/", self.get_control)
        if PHONE_DIR.is_dir():
            app.router.add_static("/phone/", PHONE_DIR, show_index=False)
        return app

    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=P.MAX_MESSAGE_BYTES)
        await ws.prepare(request)
        self.clients[ws] = "phone"        # until it says hello
        peer = request.remote
        log.info("client connected from %s", peer)
        try:
            async for raw in ws:
                if raw.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                    continue
                try:
                    msg = P.decode(raw.data)
                except P.BadMessage as e:
                    self.engine.stats["bad"] += 1
                    log.debug("bad message from %s: %s", peer, e)
                    continue
                if msg["type"] == P.HELLO:
                    role = str(msg["data"].get("role", "phone"))
                    self.clients[ws] = role if role in P.ROLES else "phone"
                    log.info("%s is %s", peer, self.clients[ws])
                    await ws.send_str(P.encode(P.make(P.STATE, self.engine.state)))
                    continue
                self.engine.handle(msg, self.clients.get(ws, "phone"))
        finally:
            self.clients.pop(ws, None)
            log.info("client %s left", peer)
        return ws

    async def post_sensor(self, request: web.Request) -> web.Response:
        try:
            body = await request.text()
            parsed = json.loads(body)
        except Exception:
            return web.json_response({"ok": False, "error": "not JSON"}, status=400)
        items = parsed if isinstance(parsed, list) else [parsed]
        n = 0
        for item in items[:100]:
            try:
                msg = P.decode(json.dumps(item))
            except P.BadMessage:
                continue
            if msg["type"] in (P.SENSOR, P.FRAME, P.ANSWER):
                self.engine.handle(msg, "phone")
                n += 1
        return web.json_response({"ok": True, "accepted": n})

    async def post_frame(self, request: web.Request) -> web.Response:
        try:
            msg = P.decode(await request.read())
        except P.BadMessage as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)
        if msg["type"] != P.FRAME:
            return web.json_response({"ok": False, "error": "expected a frame"}, status=400)
        self.engine.handle(msg, "phone")
        return web.json_response({"ok": True})

    async def get_status(self, request: web.Request) -> web.Response:
        roles: dict[str, int] = {}
        for r in self.clients.values():
            roles[r] = roles.get(r, 0) + 1
        st = self.engine.status()
        st.update({"clients": roles, "fps": round(self.fps, 1), "uptime_s": round(time.time() - self.started),
                   "udp": dict(self.udp_seq)})
        return web.json_response(st)

    async def get_control(self, request: web.Request) -> web.Response:
        if CONTROL_PAGE.exists():
            return web.FileResponse(CONTROL_PAGE)
        return web.Response(text="Infinite Jest engine running. See /status.")

    # ----------------------------------------------------------- udp
    def on_datagram(self, data: bytes) -> None:
        try:
            msg = P.decode(data)
        except P.BadMessage:
            self.engine.stats["bad"] += 1
            return
        if msg["type"] != P.SENSOR:
            return
        seq = msg["data"].get("seq")
        if isinstance(seq, int):
            if self._last_seq is not None and seq > self._last_seq + 1:
                self.udp_seq["lost"] += seq - self._last_seq - 1
            self._last_seq = seq
        self.udp_seq["received"] += 1
        self.engine.handle(msg, "phone")

    # ----------------------------------------------------------- tcp jpeg
    async def on_jpeg_stream(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("camera stream from %s", peer)
        buf = bytearray()
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                buf += chunk
                for jpeg in split_jpegs(buf):
                    self.engine.on_jpeg(jpeg)
                if len(buf) > MAX_JPEG_BUFFER:
                    del buf[:]   # garbage on the line; start over
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            buf.clear()
            writer.close()
            log.info("camera stream %s closed", peer)

    # ----------------------------------------------------------- lifecycle
    async def start(self) -> None:
        net = self.cfg["network"]
        host, port = net.get("host", "0.0.0.0"), int(net.get("port", 8765))
        self._runner = web.AppRunner(self.app(), access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, host, port).start()
        log.info("hub on http://%s:%d  (ws at /ws)", host, port)
        loop = asyncio.get_running_loop()
        if int(net.get("udp_port", 0)):
            hub = self

            class _Udp(asyncio.DatagramProtocol):
                def datagram_received(self, data, addr):  # noqa: N802
                    hub.on_datagram(data)

            self._udp, _ = await loop.create_datagram_endpoint(_Udp, local_addr=(host, int(net["udp_port"])))
            log.info("udp sensors on %d", int(net["udp_port"]))
        if int(net.get("tcp_port", 0)):
            self._tcp = await asyncio.start_server(self.on_jpeg_stream, host, int(net["tcp_port"]))
            log.info("tcp camera stream on %d", int(net["tcp_port"]))

    async def stop(self) -> None:
        for ws in list(self.clients):
            await ws.close()
        if self._udp is not None:
            self._udp.close()
        if self._tcp is not None:
            self._tcp.close()
        if self._runner is not None:
            await self._runner.cleanup()


def split_jpegs(buf: bytearray) -> list[bytes]:
    """Pull complete JPEGs (FFD8 ... FFD9) out of the front of buf, in place."""
    out = []
    while True:
        start = buf.find(b"\xff\xd8")
        if start < 0:
            # keep a trailing 0xFF in case the marker is split across reads
            keep = buf[-1:] if buf[-1:] == b"\xff" else b""
            buf[:] = keep
            return out
        end = buf.find(b"\xff\xd9", start + 2)
        if end < 0:
            if start:
                del buf[:start]
            return out
        out.append(bytes(buf[start:end + 2]))
        del buf[:end + 2]
