# -*- coding: utf-8 -*-
"""Network transports from the N900 to the Pi (see CONTRACT.md, "Ports").

- WSClient: a hand-rolled WebSocket client (RFC 6455, text frames only) for
  Python 2.5, which has no WebSocket library. This is the main lane, because
  it is the only one that also carries messages back to the phone (state,
  phone prompts, wipe).
- UDPSender: the fallback lane for sensor envelopes (Pi port 8766), used
  while the WebSocket is down so the show still gets the phone's readings.

Client-to-server frames must be masked. We use a zero mask key: the RFC
wants an unpredictable key to protect old HTTP proxies, which do not exist
on this closed LAN, and a zero key leaves the payload unchanged, so the
600 MHz phone never XORs 20 KB camera frames in Python. Every server
(aiohttp, websockets) accepts it because it just XORs with zeros.
"""

import socket
import struct
import base64
import os
import threading
import time

from compat import to_bytes, to_text, byte_at, bchr, EMPTY, exc, log, dumps

CRLF2 = to_bytes('\r\n\r\n')
# Engine messages are small JSON (state, phone text). Anything bigger is a
# broken or hostile peer: drop the link instead of filling the phone's RAM.
MAX_MESSAGE = 256 * 1024
ZERO_MASK = to_bytes('\x00\x00\x00\x00')


class WSClosed(Exception):
    pass


class WSClient(object):

    def __init__(self, host, port, path='/ws', timeout=5.0, max_message=MAX_MESSAGE):
        self.host = host
        self.port = int(port)
        self.path = path
        self.timeout = timeout
        self.sock = None
        self.lock = threading.Lock()
        self.buf = EMPTY
        self.open = False
        self.max_message = max_message

    # -------------------------------------------------------- connect --
    def connect(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        try:
            s.connect((self.host, self.port))
        except Exception:
            s.close()  # don't leak a file descriptor per failed attempt over days
            raise
        key = to_text(base64.b64encode(os.urandom(16)))
        req = ('GET %s HTTP/1.1\r\n'
               'Host: %s:%d\r\n'
               'Upgrade: websocket\r\n'
               'Connection: Upgrade\r\n'
               'Sec-WebSocket-Key: %s\r\n'
               'Sec-WebSocket-Version: 13\r\n'
               'User-Agent: ij-phone-n900\r\n'
               '\r\n') % (self.path, self.host, self.port, key)
        s.sendall(to_bytes(req))
        head = EMPTY
        while CRLF2 not in head:
            chunk = s.recv(1024)
            if not chunk:
                s.close()
                raise WSClosed('closed during handshake')
            head += chunk
            if len(head) > 16384:
                s.close()
                raise WSClosed('handshake too long')
        idx = head.find(CRLF2)
        status = to_text(head[:idx]).split('\r\n')[0]
        if ' 101' not in status:
            s.close()
            raise WSClosed('handshake refused: ' + status)
        self.buf = head[idx + 4:]
        # Reads block for up to 1 s so the reader thread can notice a stop.
        s.settimeout(1.0)
        self.sock = s
        self.open = True

    def close(self):
        self.open = False
        s = self.sock
        self.sock = None
        if s is not None:
            try:
                self._send_frame(0x8, EMPTY, s)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    # ---------------------------------------------------------- send ---
    def _send_frame(self, opcode, payload, sock=None):
        s = sock or self.sock
        if s is None:
            raise WSClosed('not connected')
        n = len(payload)
        head = bchr(0x80 | opcode)
        if n < 126:
            head += bchr(0x80 | n)
        elif n < 65536:
            head += bchr(0x80 | 126) + struct.pack('!H', n)
        else:
            head += bchr(0x80 | 127) + struct.pack('!Q', n)
        self.lock.acquire()
        try:
            s.sendall(head + ZERO_MASK + payload)
        finally:
            self.lock.release()

    def send_text(self, text):
        try:
            self._send_frame(0x1, to_bytes(text))
        except socket.error:
            self.open = False
            raise WSClosed(str(exc()))

    def send_json(self, obj):
        self.send_text(dumps(obj))

    # ---------------------------------------------------------- recv ---
    def _read(self, n):
        while len(self.buf) < n:
            if not self.open or self.sock is None:
                raise WSClosed('closed')
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            except socket.error:
                self.open = False
                raise WSClosed(str(exc()))
            if not chunk:
                self.open = False
                raise WSClosed('server closed')
            self.buf += chunk
        out = self.buf[:n]
        self.buf = self.buf[n:]
        return out

    def recv_text(self):
        """Block until one complete text message arrives; answer pings."""
        parts = []
        total = 0
        while True:
            h = self._read(2)
            b0 = byte_at(h, 0)
            b1 = byte_at(h, 1)
            fin = b0 & 0x80
            op = b0 & 0x0f
            n = b1 & 0x7f
            if n == 126:
                n = struct.unpack('!H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('!Q', self._read(8))[0]
            if n > self.max_message or total + n > self.max_message:
                self.open = False
                raise WSClosed('message too big (%d bytes)' % (total + n))
            mask = None
            if b1 & 0x80:
                mask = self._read(4)
            payload = n and self._read(n) or EMPTY
            if mask is not None and n:
                payload = EMPTY.join([bchr(byte_at(payload, i) ^ byte_at(mask, i % 4))
                                      for i in range(n)])
            if op == 0x8:
                self.open = False
                raise WSClosed('close frame')
            if op == 0x9:
                try:
                    self._send_frame(0xA, payload)
                except Exception:
                    pass
                continue
            if op == 0xA:
                continue
            if op in (0x0, 0x1, 0x2):
                parts.append(payload)
                total += n
                if fin:
                    return to_text(EMPTY.join(parts))


class UDPSender(object):
    """Fire-and-forget JSON envelopes to the Pi's UDP lane (port 8766)."""

    def __init__(self, host, port):
        self.addr = (host, int(port))
        self.host = host
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0

    def send_json(self, obj):
        self.seq += 1
        try:
            obj['data']['seq'] = self.seq
        except Exception:
            pass
        data = to_bytes(dumps(obj))
        if len(data) > 60000:
            return  # frames never go over UDP
        try:
            self.sock.sendto(data, self.addr)
        except socket.error:
            pass

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def resolve(host):
    try:
        return socket.gethostbyname(host)
    except Exception:
        return None


def now():
    return time.time()
