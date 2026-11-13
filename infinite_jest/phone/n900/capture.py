# -*- coding: utf-8 -*-
"""Camera and microphone capture on the N900 through gst-launch-0.10.

We run GStreamer as a child process that writes raw bytes to its stdout and
read them in a thread, so the agent needs no gst-python bindings.

Camera: front camera (/dev/video1, faces whoever holds or looks at the
phone) as 8-bit grayscale. The phone computes a cheap motion and brightness
value itself and keeps only the latest frame in RAM, for the agent to send
to the Pi. Nothing is ever written to disk.

Microphone: 8 kHz mono 16-bit. Only a level and a crude "voiced" flag leave
this module. The audio itself is dropped right after it is measured: no
recording, no words (see CONTRACT.md, privacy).

FAKE=1 in the environment (or fake=True) swaps both for synthetic sources so
the whole agent runs on a laptop.
"""

import math
import os
import random
import subprocess
import threading
import time
from array import array

from compat import clamp, log, exc, EMPTY

GST = os.environ.get('IJ_GST', 'gst-launch-0.10')

# Tried in order; the agent moves to the next one when a pipeline keeps failing.
# 1) raw UYVY at 2x the target size; Python keeps every other luma byte, so no
#    colour conversion runs on the phone. 2) GStreamer converts to gray itself.
CAMERA_PIPELINES = [
    ('uyvy', '%(gst)s -q v4l2camsrc device=%(device)s ! '
             'video/x-raw-yuv,format=(fourcc)UYVY,width=%(w2)d,height=%(h2)d ! '
             'videorate ! video/x-raw-yuv,framerate=%(fps)d/1 ! '
             'fdsink fd=1 sync=false'),
    ('gray', '%(gst)s -q v4l2camsrc device=%(device)s ! '
             'video/x-raw-yuv,width=320,height=240 ! '
             'videorate ! video/x-raw-yuv,framerate=%(fps)d/1 ! '
             'ffmpegcolorspace ! videoscale ! '
             'video/x-raw-gray,bpp=8,depth=8,width=%(w)d,height=%(h)d ! '
             'fdsink fd=1 sync=false'),
    ('gray', '%(gst)s -q v4l2src device=%(device)s ! '
             'ffmpegcolorspace ! videoscale ! '
             'video/x-raw-gray,bpp=8,depth=8,width=%(w)d,height=%(h)d ! '
             'videorate ! video/x-raw-gray,framerate=%(fps)d/1 ! '
             'fdsink fd=1 sync=false'),
]

MIC_PIPELINE = (
    '%(gst)s -q pulsesrc ! '
    'audio/x-raw-int,rate=8000,channels=1,width=16,depth=16,signed=true,endianness=1234 ! '
    'fdsink fd=1 sync=false'
)


def _read_exact(f, n):
    parts = []
    left = n
    while left > 0:
        d = f.read(left)
        if not d:
            return None
        parts.append(d)
        left -= len(d)
    return EMPTY.join(parts)


class _Child(object):
    """Keeps one gst-launch child alive and hands fixed-size chunks to `on_chunk`."""

    def __init__(self, name, cmds, on_chunk, retry=3.0):
        # cmds: list of (mode, command, chunk_size); we stay on one that works
        self.name = name
        self.cmds = cmds
        self.idx = 0
        self.fails = 0
        self.mode = cmds[0][0]
        self.on_chunk = on_chunk
        self.retry = retry
        self.proc = None
        self.running = False
        self.ok = False

    def start(self):
        self.running = True
        t = threading.Thread(target=self._loop)
        t.setDaemon(True)
        t.start()

    def stop(self):
        self.running = False
        p = self.proc
        if p is not None:
            try:
                os.kill(p.pid, 15)
            except Exception:
                pass

    def _loop(self):
        while self.running:
            mode, cmd, chunk = self.cmds[self.idx]
            self.mode = mode
            got = 0
            try:
                log(self.name, 'starting:', cmd)
                devnull = open(os.devnull, 'w')
                self.proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE,
                                             stderr=devnull, bufsize=0)
                out = self.proc.stdout
                while self.running:
                    data = _read_exact(out, chunk)
                    if data is None:
                        break
                    self.ok = True
                    got += 1
                    self.on_chunk(data, mode)
            except Exception:
                log(self.name, 'error:', exc())
            self.ok = False
            if got < 3:
                self.fails += 1
                if self.fails >= 2 and len(self.cmds) > 1:
                    self.idx = (self.idx + 1) % len(self.cmds)
                    self.fails = 0
                    log(self.name, 'switching to pipeline', self.idx)
            else:
                self.fails = 0
            try:
                if self.proc is not None:
                    os.kill(self.proc.pid, 15)
                    self.proc.wait()
            except Exception:
                pass
            if self.running:
                log(self.name, 'stopped, retrying in', self.retry, 's')
                time.sleep(self.retry)


class Camera(object):

    def __init__(self, w=160, h=120, fps=4, device='/dev/video1', fake=False, cmd=None):
        self.w = w
        self.h = h
        self.fps = fps
        self.fake = fake
        self.lock = threading.Lock()
        self.frame = None          # latest raw gray8 bytes (RAM only)
        self.frame_t = 0.0
        self.frame_seq = 0
        self.motion = 0.0
        self.brightness = 0.0
        self.prev = None
        self.step = 4               # sample every 4th pixel for the motion estimate
        v = {'gst': GST, 'device': device, 'fps': fps, 'w': w, 'h': h, 'w2': w * 2, 'h2': h * 2}
        if cmd:
            cmds = [('gray', cmd, w * h)]
        else:
            cmds = []
            for mode, c in CAMERA_PIPELINES:
                cmds.append((mode, c % v, mode == 'uyvy' and (w * 2) * (h * 2) * 2 or w * h))
        self.child = None
        if not fake:
            self.child = _Child('camera', cmds, self._on_frame)

    def start(self):
        if self.fake:
            t = threading.Thread(target=self._fake_loop)
            t.setDaemon(True)
            t.start()
        else:
            self.child.start()

    def stop(self):
        if self.child:
            self.child.stop()

    def alive(self):
        if self.fake:
            return True
        return self.child.ok

    def _on_frame(self, data, mode='gray'):
        if mode == 'uyvy':
            # U Y0 V Y1 ...: every 4th byte from 1 is one luma per pixel pair,
            # every other row: a (w*2)x(h*2) UYVY frame becomes w x h gray.
            row = self.w * 2 * 2
            data = EMPTY.join([data[i + 1:i + row:4] for i in range(0, row * self.h * 2, row * 2)])
        px = array('B', data)
        w, h, st = self.w, self.h, self.step
        sample = []
        total = 0
        for y in range(st // 2, h, st):
            row = y * w
            for x in range(st // 2, w, st):
                v = px[row + x]
                sample.append(v)
                total += v
        n = len(sample) or 1
        motion = 0.0
        prev = self.prev
        if prev is not None and len(prev) == len(sample):
            diff = 0
            for i in range(len(sample)):
                d = sample[i] - prev[i]
                if d < 0:
                    d = -d
                if d > 12:          # ignore sensor noise
                    diff += d
            motion = clamp(diff / (n * 40.0))
        self.prev = sample
        self.lock.acquire()
        try:
            self.frame = data
            self.frame_t = time.time()
            self.frame_seq += 1
            self.motion = 0.6 * self.motion + 0.4 * motion
            self.brightness = total / (n * 255.0)
        finally:
            self.lock.release()

    def latest(self):
        self.lock.acquire()
        try:
            return self.frame, self.frame_seq
        finally:
            self.lock.release()

    def wipe(self):
        self.lock.acquire()
        try:
            self.frame = None
            self.prev = None
            self.motion = 0.0
        finally:
            self.lock.release()

    def _fake_loop(self):
        t0 = time.time()
        while True:
            t = time.time() - t0
            cx = int((math.sin(t * 0.7) * 0.4 + 0.5) * self.w)
            rows = []
            for y in range(self.h):
                row = []
                for x in range(self.w):
                    d = abs(x - cx) + abs(y - self.h // 2)
                    row.append(d < 25 and 200 or 30)
                rows.extend(row)
            a = array('B', rows)
            self._on_frame(hasattr(a, 'tobytes') and a.tobytes() or a.tostring())
            time.sleep(1.0 / self.fps)


class Mic(object):
    """Level 0..1 and a voiced flag. Audio samples are discarded immediately."""

    RATE = 8000
    CHUNK = 400  # samples = 50 ms

    def __init__(self, fake=False, cmd=None, gain=1.0):
        self.fake = fake
        self.gain = gain
        self.level = 0.0
        self.voiced = False
        self.voice_score = 0.0
        self.floor = 0.01
        self.lock = threading.Lock()
        cmd = cmd or MIC_PIPELINE % {'gst': GST}
        self.child = None
        if not fake:
            self.child = _Child('mic', [('pcm', cmd, self.CHUNK * 2)], self._on_chunk)

    def start(self):
        if self.fake:
            t = threading.Thread(target=self._fake_loop)
            t.setDaemon(True)
            t.start()
        else:
            self.child.start()

    def stop(self):
        if self.child:
            self.child.stop()

    def alive(self):
        return self.fake or self.child.ok

    def _on_chunk(self, data, mode='pcm'):
        s = array('h', data)
        n = len(s)
        if not n:
            return
        acc = 0
        zc = 0
        last = s[0]
        for v in s:
            acc += v * v
            if (v >= 0) != (last >= 0):
                zc += 1
            last = v
        rms = math.sqrt(acc / float(n)) / 32768.0
        zcr = zc / float(n)
        del s, data  # nothing of the sound is kept
        # slow noise floor that follows the room's hum down fast and up slowly
        if rms < self.floor:
            self.floor = 0.9 * self.floor + 0.1 * rms
        else:
            self.floor = 0.999 * self.floor + 0.001 * rms
        # dB-ish scale: -60 dBFS -> 0, -10 dBFS -> 1
        db = 20.0 * math.log10(max(rms * self.gain, 1e-6))
        level = clamp((db + 60.0) / 50.0)
        # Speech at 8 kHz: clearly above the floor and a zero-crossing rate in
        # a voice-like band (hiss is higher, hum is lower). Crude on purpose.
        above = rms > self.floor * 3.0 and rms > 0.003
        voicey = 0.02 < zcr < 0.25
        score = (above and voicey) and 1.0 or 0.0
        self.lock.acquire()
        try:
            self.level = 0.5 * self.level + 0.5 * level
            self.voice_score = 0.8 * self.voice_score + 0.2 * score
            self.voiced = self.voice_score > 0.5
        finally:
            self.lock.release()

    def _fake_loop(self):
        t0 = time.time()
        while True:
            t = time.time() - t0
            amp = (math.sin(t * 0.5) > 0.3) and 6000 or 80
            freq = 180.0
            s = array('h', [int(amp * math.sin(2 * math.pi * freq * i / self.RATE)
                                + random.randint(-60, 60)) for i in range(self.CHUNK)])
            self._on_chunk(hasattr(s, 'tobytes') and s.tobytes() or s.tostring())
            time.sleep(self.CHUNK / float(self.RATE))
