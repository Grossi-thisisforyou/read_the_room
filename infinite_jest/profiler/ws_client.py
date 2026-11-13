"""Run the profiler as its own process on the Pi, talking to the engine.

Uses the `websockets` package if installed, otherwise a tiny stdlib client
(ws:// only, text frames, which is all the contract needs). Reconnects
forever, so it can be started before the engine.
"""

import base64
import json
import os
import socket
import struct
import sys
import time
from urllib.parse import urlparse

from .core import create


class MiniWS:
    def __init__(self, url, timeout=10):
        u = urlparse(url)
        if u.scheme != "ws":
            raise ValueError("only ws:// is supported by the stdlib client")
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + ("?" + u.query if u.query else "")
        req = ("GET {} HTTP/1.1\r\nHost: {}:{}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n").format(
                   path, u.hostname, u.port or 80, key)
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("server refused websocket: " + head.split(b"\r\n", 1)[0].decode())
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.sock.settimeout(None)

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        """Return the next text message as str (handles ping/close)."""
        parts = []
        while True:
            b1, b2 = self._read(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
            if op == 0x8:
                raise ConnectionError("server closed")
            if op == 0x9:
                self._send(0xA, payload)
                continue
            if op in (0x1, 0x0, 0x2):
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode("utf-8", "replace")

    def _send(self, op, payload):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            head = struct.pack(">BB", 0x80 | op, 0x80 | n)
        elif n < 65536:
            head = struct.pack(">BBH", 0x80 | op, 0x80 | 126, n)
        else:
            head = struct.pack(">BBQ", 0x80 | op, 0x80 | 127, n)
        self.sock.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))

    def send(self, text):
        self._send(0x1, text.encode())

    def close(self):
        try:
            self._send(0x8, b"")
            self.sock.close()
        except OSError:
            pass


HELLO = {"type": "hello", "ts": 0, "data": {"role": "profiler", "name": "infinite_jest.profiler",
                                            "version": "1.0"}}


def run_forever(url, debug=False):
    profiler = create()
    while True:
        try:
            ws = MiniWS(url)
            ws.send(json.dumps(dict(HELLO, ts=time.time())))
            print("profiler: connected to", url, file=sys.stderr)
            while True:
                try:
                    m = json.loads(ws.recv())
                except ValueError:
                    continue
                for out in profiler.handle(m):
                    ws.send(json.dumps(out))
                    if debug and out["type"] == "profile":
                        d = out["data"]
                        print(d.get("phase"), d.get("hook"), d.get("confidence"),
                              d.get("ocean"), file=sys.stderr)
        except KeyboardInterrupt:
            profiler.reset()
            return 0
        except (OSError, ConnectionError) as e:
            profiler.reset()  # losing the engine = end of visit; forget everything
            print("profiler: {} - retrying in 2 s".format(e), file=sys.stderr)
            time.sleep(2)
