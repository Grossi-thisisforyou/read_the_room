"""The N900 agent against a hostile fake engine, over real sockets.

A raw-socket WebSocket server (no library, so it can misbehave on purpose):
the engine down at boot, the engine sending garbage / unknown / oversized
messages, the engine that stops reading (TCP window full), and restarts.

    cd infinite_jest/phone && python3 -m pytest -q tests/test_hostile_net.py
"""
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'n900'))

from agent import Agent, DEFAULTS  # noqa: E402
from sensors import PATHS  # noqa: E402
from transport import WSClient, WSClosed  # noqa: E402

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def free_port(kind=socket.SOCK_STREAM):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def fake_sysfs():
    root = tempfile.mkdtemp()
    for k, v in ((PATHS['accel'], '18 -36 -1008'), (PATHS['proximity'], 'open'),
                 (PATHS['lux'], '35')):
        os.makedirs(os.path.dirname(root + k), exist_ok=True)
        open(root + k, 'w').write(v)
    return root


def frame(op, payload, fin=True):
    n = len(payload)
    b0 = (0x80 if fin else 0) | op
    if n < 126:
        h = struct.pack('!BB', b0, n)
    elif n < 65536:
        h = struct.pack('!BBH', b0, 126, n)
    else:
        h = struct.pack('!BBQ', b0, 127, n)
    return h + payload


class RawServer(object):
    """Accepts WebSocket clients; `behave(conn)` runs per connection."""

    def __init__(self, behave, port=None):
        self.behave = behave
        self.port = port or free_port()
        self.ls = socket.socket()
        self.ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ls.bind(('127.0.0.1', self.port))
        self.ls.listen(8)
        self.accepts = 0
        self.conns = []
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            try:
                c, _ = self.ls.accept()
            except OSError:
                return
            self.accepts += 1
            self.conns.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        try:
            head = b''
            while b'\r\n\r\n' not in head:
                d = c.recv(1024)
                if not d:
                    return
                head += d
            key = [ln.split(b':', 1)[1].strip() for ln in head.split(b'\r\n')
                   if ln.lower().startswith(b'sec-websocket-key')][0]
            acc = base64.b64encode(hashlib.sha1(key + GUID.encode()).digest())
            c.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                      b'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + acc + b'\r\n\r\n')
            self.behave(c)
        except OSError:
            pass

    def close(self):
        self.running = False
        try:
            self.ls.shutdown(socket.SHUT_RDWR)   # wakes accept(); close() alone doesn't
        except OSError:
            pass
        try:
            self.ls.close()
        except OSError:
            pass
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)   # what a dying engine's kernel does
            except OSError:
                pass
            try:
                c.close()
            except OSError:
                pass


def read_frames(c, sink, stop):
    """Read client frames (masked) into sink as decoded text."""
    buf = b''
    c.settimeout(0.5)
    while not stop():
        try:
            d = c.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            return
        if not d:
            return
        buf += d
        while len(buf) >= 2:
            n = buf[1] & 0x7f
            off = 2
            if n == 126:
                if len(buf) < 4:
                    break
                n = struct.unpack('!H', buf[2:4])[0]
                off = 4
            elif n == 127:
                if len(buf) < 10:
                    break
                n = struct.unpack('!Q', buf[2:10])[0]
                off = 10
            if buf[1] & 0x80:
                mask = buf[off:off + 4]
                off += 4
            else:
                mask = b'\0\0\0\0'
            if len(buf) < off + n:
                break
            p = bytes(b ^ mask[i % 4] for i, b in enumerate(buf[off:off + n]))
            buf = buf[off + n:]
            sink.append(p.decode('utf-8', 'replace'))


def make_agent(ws_port, udp_port, **kw):
    conf = dict(DEFAULTS, hosts='127.0.0.1', ws_port=ws_port, udp_port=udp_port,
                keep_awake=0, **kw)
    return Agent(conf, fake=True, sysfs_root=fake_sysfs())


def udp_sink(port):
    got = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', port))
    s.settimeout(0.5)

    def loop():
        while True:
            try:
                d, _ = s.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            got.append(json.loads(d))
    threading.Thread(target=loop, daemon=True).start()
    return got, s


# ------------------------------------------------------------------ tests --

def test_engine_down_at_boot_udp_and_gentle_retries():
    """The Pi boots slower than the phone: UDP lane carries readings and the
    WebSocket retries back off (no tight loop draining the battery)."""
    ws_port, udp_port = free_port(), free_port(socket.SOCK_DGRAM)
    got, us = udp_sink(udp_port)
    # A port that accepts TCP then closes at once (handshake fails)
    ls = socket.socket()
    ls.bind(('127.0.0.1', ws_port))
    ls.listen(8)
    n = [0]

    def acc():
        while True:
            try:
                c, _ = ls.accept()
            except OSError:
                return
            n[0] += 1
            c.close()
    threading.Thread(target=acc, daemon=True).start()
    a = make_agent(ws_port, udp_port)
    a.start()
    time.sleep(12)
    a.stop()
    ls.close()
    us.close()
    assert len(got) > 50, 'UDP lane while the WebSocket is down (%d)' % len(got)
    assert all(m['data'].get('seq') for m in got[:5])
    assert n[0] <= 8, 'WebSocket attempts in 12 s: %d (tight loop)' % n[0]
    assert a.events.qsize() < 200


def test_garbage_unknown_and_oversized_messages_do_not_kill_the_agent():
    ws_port, udp_port = free_port(), free_port(socket.SOCK_DGRAM)
    got_ws = []
    stop = [False]

    def behave(c):
        threading.Thread(target=read_frames, args=(c, got_ws, lambda: stop[0]), daemon=True).start()
        junk = [b'not json at all', b'[1,2,3]', b'{"type": 7}', b'{"type":"phone","data":[1]}',
                b'{"type":"teleport","ts":0,"data":{}}', b'\xff\xfe\x00garbage',
                b'{"type":"phone","data":{"text":{"a":1},"ask":5,"options":"ab"}}',
                b'{"type":"phone","data":{"ask":"q?","options":[null,{"x":1}]}}',
                b'{"type":"state","ts":"soon","data":{"phase":"idle","mode":"fixed"}}',
                b'{"type":"phone","ts":0,"data":{"text":"' + b'A' * 100000 + b'"}}',
                b'{"type":"phone","ts":0,"data":{"text":"still alive"}}']
        for j in junk:
            c.sendall(frame(0x1, j))
            time.sleep(0.05)
        c.sendall(frame(0x9, b'ping'))        # ping must be answered, not shown
        c.sendall(frame(0x2, b'\x00\x01'))    # binary
        time.sleep(1.0)
        # a 2 MB message: the agent must drop the link, not buffer it
        c.sendall(frame(0x1, b'x' * (2 * 1024 * 1024)))
        while not stop[0]:
            time.sleep(0.2)

    srv = RawServer(behave, ws_port)
    a = make_agent(ws_port, udp_port)
    a.start()
    time.sleep(3.0)
    snap = a.ui_snapshot()
    assert snap['text'] == 'still alive'
    assert len(got_ws) > 10
    time.sleep(5.0)
    stop[0] = True
    a.stop()
    srv.close()
    assert srv.accepts >= 2, 'did not drop and reconnect after a 2 MB message'
    assert a.ui_snapshot()['prompt'] is None or isinstance(a.ui_snapshot()['prompt']['ask'], str)


def test_engine_stops_reading_ui_never_blocks_and_agent_recovers():
    """The Pi is wedged (accepts, never reads: TCP window fills up with 4 fps
    frames). Touches from the GTK thread must return at once, readings for
    the screen keep updating, and the agent reconnects when the Pi is back."""
    ws_port, udp_port = free_port(), free_port(socket.SOCK_DGRAM)
    wedged = [True]
    got_ws = []

    def behave(c):
        c.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        if wedged[0]:
            while wedged[0]:
                time.sleep(0.1)      # never read
            c.close()
            return
        read_frames(c, got_ws, lambda: False)

    srv = RawServer(behave, ws_port)
    a = make_agent(ws_port, udp_port)
    updates = []
    orig = a.ui_update

    def spy(**kw):
        if 'reading' in kw:
            updates.append(time.time())
        orig(**kw)
    a.ui_update = spy
    a.start()
    worst_touch = 0.0
    t_end = time.time() + 12
    while time.time() < t_end:
        t0 = time.time()
        a.on_touch(0.5, 0.5, True)
        a.ui_snapshot()
        worst_touch = max(worst_touch, time.time() - t0)
        time.sleep(0.05)
    gaps = [b - a_ for a_, b in zip(updates, updates[1:])]
    wedged[0] = False
    time.sleep(8)
    a.stop()
    srv.close()
    assert worst_touch < 0.1, 'GTK-side call blocked %.2f s' % worst_touch
    assert max(gaps) < 2.5, 'screen readout froze for %.1f s' % max(gaps)
    assert a.events.qsize() <= 200
    assert any('"phone"' in m for m in got_ws), 'no readings after the Pi un-wedged'


def test_engine_restart_mid_visit_reconnects_and_keeps_the_visitor_screen():
    ws_port, udp_port = free_port(), free_port(socket.SOCK_DGRAM)
    got1, got2 = [], []
    stop = [False]
    srv = RawServer(lambda c: read_frames(c, got1, lambda: stop[0]), ws_port)
    a = make_agent(ws_port, udp_port)
    a.start()
    time.sleep(2)
    a.on_consent()
    srv.close()
    stop[0] = True
    time.sleep(3)
    assert a.link == 'udp'
    stop[0] = False
    srv2 = RawServer(lambda c: read_frames(c, got2, lambda: stop[0]), ws_port)
    time.sleep(12)
    stop[0] = True
    a.stop()
    srv2.close()
    assert any('"hello"' in m for m in got2), 'no reconnect after the engine restart'
    assert a.ui_snapshot()['screen'] == 'live'


def test_wsclient_rejects_oversized_frame_header_without_allocating():
    """A frame header claiming 2^62 bytes must fail fast (not try to buffer it)."""
    port = free_port()

    def behave(c):
        c.sendall(struct.pack('!BBQ', 0x81, 127, 1 << 62))
        time.sleep(1)
    srv = RawServer(behave, port)
    ws = WSClient('127.0.0.1', port, timeout=2)
    ws.connect()
    t0 = time.time()
    try:
        ws.recv_text()
        raised = False
    except WSClosed:
        raised = True
    srv.close()
    assert raised and time.time() - t0 < 2
