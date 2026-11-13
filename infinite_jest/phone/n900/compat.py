# -*- coding: utf-8 -*-
"""Python 2.5 / Python 3 helpers for the INFINITE JEST phone agent.

The Nokia N900 ships Python 2.5 (Maemo 5). Python 2.5 has no `json`, no b''
literals, no `except X as e` and no bytearray, so every module in this folder
sticks to syntax that parses on both 2.5 and 3.x, and uses these helpers for
bytes, text and JSON. The tests run the same files on Python 3.
"""

import sys
import math

PY3 = sys.version_info[0] >= 3

if PY3:
    text_type = str
    string_types = (str,)
    integer_types = (int,)

    def to_bytes(s):
        if isinstance(s, bytes):
            return s
        return s.encode('utf-8')

    def to_text(b):
        if isinstance(b, str):
            return b
        return b.decode('utf-8', 'replace')

    def byte_at(b, i):
        return b[i]

    def bchr(n):
        return bytes((n,))

    try:
        import queue as queue_mod
    except ImportError:
        queue_mod = None
else:
    text_type = unicode  # noqa: F821 (Python 2 only)
    string_types = (str, unicode)  # noqa: F821
    integer_types = (int, long)  # noqa: F821

    def to_bytes(s):
        if isinstance(s, unicode):  # noqa: F821
            return s.encode('utf-8')
        return s

    def to_text(b):
        if isinstance(b, unicode):  # noqa: F821
            return b
        return b.decode('utf-8', 'replace')

    def byte_at(b, i):
        return ord(b[i])

    def bchr(n):
        return chr(n)

    import Queue as queue_mod  # noqa: F401


EMPTY = to_bytes('')


def exc():
    """The current exception, without `except X as e` (not valid in 2.5)."""
    return sys.exc_info()[1]


def log(*parts):
    msg = ' '.join([str(p) for p in parts])
    try:
        sys.stderr.write('[ij-phone] ' + msg + '\n')
        sys.stderr.flush()
    except Exception:
        pass


def clamp(v, lo=0.0, hi=1.0):
    if v != v:  # NaN
        return lo
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


# ---------------------------------------------------------------- JSON ----

try:
    import json as _json
except ImportError:
    try:
        import simplejson as _json
    except ImportError:
        _json = None


def _enc_str(s):
    u = to_text(s)
    out = ['"']
    for ch in u:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif o < 0x20 or o > 0x7e:
            if o > 0xffff:
                o -= 0x10000
                out.append('\\u%04x\\u%04x' % (0xd800 + (o >> 10), 0xdc00 + (o & 0x3ff)))
            else:
                out.append('\\u%04x' % o)
        else:
            out.append(str(ch))
    out.append('"')
    return ''.join(out)


def _enc_num(v):
    if isinstance(v, bool):
        return v and 'true' or 'false'
    if isinstance(v, integer_types):
        return str(v)
    if v != v or v in (float('inf'), float('-inf')):
        return 'null'
    s = '%.4f' % v
    s = s.rstrip('0').rstrip('.')
    if s in ('', '-', '-0'):
        s = '0'
    return s


def dumps(obj):
    """Compact JSON. Floats are rounded to 4 decimals to keep packets small."""
    if obj is None:
        return 'null'
    if isinstance(obj, bool) or isinstance(obj, integer_types) or isinstance(obj, float):
        return _enc_num(obj)
    if isinstance(obj, string_types) or (PY3 and isinstance(obj, bytes)):
        return _enc_str(obj)
    if isinstance(obj, dict):
        items = []
        for k in obj:
            items.append(_enc_str(k) + ':' + dumps(obj[k]))
        return '{' + ','.join(items) + '}'
    if isinstance(obj, (list, tuple)):
        return '[' + ','.join([dumps(x) for x in obj]) + ']'
    return _enc_str(str(obj))


class _Parser(object):
    """Tiny JSON parser, used only when neither json nor simplejson exists."""

    def __init__(self, s):
        self.s = to_text(s)
        self.i = 0

    def ws(self):
        s = self.s
        n = len(s)
        while self.i < n and s[self.i] in ' \t\r\n':
            self.i += 1

    def parse(self):
        self.ws()
        v = self.value()
        self.ws()
        return v

    def value(self):
        self.ws()
        c = self.s[self.i]
        if c == '{':
            return self.obj()
        if c == '[':
            return self.arr()
        if c == '"':
            return self.string()
        if self.s.startswith('true', self.i):
            self.i += 4
            return True
        if self.s.startswith('false', self.i):
            self.i += 5
            return False
        if self.s.startswith('null', self.i):
            self.i += 4
            return None
        return self.number()

    def obj(self):
        self.i += 1
        d = {}
        self.ws()
        if self.s[self.i] == '}':
            self.i += 1
            return d
        while True:
            self.ws()
            k = self.string()
            self.ws()
            self.i += 1  # ':'
            d[k] = self.value()
            self.ws()
            c = self.s[self.i]
            self.i += 1
            if c == '}':
                return d

    def arr(self):
        self.i += 1
        a = []
        self.ws()
        if self.s[self.i] == ']':
            self.i += 1
            return a
        while True:
            a.append(self.value())
            self.ws()
            c = self.s[self.i]
            self.i += 1
            if c == ']':
                return a

    def string(self):
        self.i += 1
        s = self.s
        out = []
        while True:
            c = s[self.i]
            if c == '"':
                self.i += 1
                return ''.join(out)
            if c == '\\':
                e = s[self.i + 1]
                self.i += 2
                if e == 'u':
                    code = int(s[self.i:self.i + 4], 16)
                    self.i += 4
                    if 0xd800 <= code < 0xdc00 and s[self.i:self.i + 2] == '\\u':
                        lo = int(s[self.i + 2:self.i + 6], 16)
                        self.i += 6
                        code = 0x10000 + ((code - 0xd800) << 10) + (lo - 0xdc00)
                    try:
                        out.append(unichr(code))  # noqa: F821 (py2)
                    except NameError:
                        out.append(chr(code))
                    except ValueError:
                        out.append('?')
                else:
                    out.append({'n': '\n', 't': '\t', 'r': '\r', 'b': '\b',
                                'f': '\f'}.get(e, e))
            else:
                out.append(c)
                self.i += 1

    def number(self):
        s = self.s
        j = self.i
        n = len(s)
        while j < n and s[j] in '+-0123456789.eE':
            j += 1
        tok = s[self.i:j]
        self.i = j
        if '.' in tok or 'e' in tok or 'E' in tok:
            return float(tok)
        return int(tok)


def loads(s):
    if _json is not None:
        return _json.loads(to_text(s))
    return _Parser(s).parse()


def atan2deg(y, x):
    return math.degrees(math.atan2(y, x))
