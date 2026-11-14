# -*- coding: utf-8 -*-
"""Cheap N900 sensors read straight from sysfs (no root needed).

Paths are the Maemo 5 Fremantle ones. Every path is configurable, and
`root` lets the tests point everything at a fake directory tree.
A missing file just means that reading is left out of the message.
"""

import math
import os

from compat import clamp, atan2deg, finite

PATHS = {
    'accel': '/sys/class/i2c-adapter/i2c-3/3-001d/coord',          # "x y z" milli-g
    'lux': '/sys/class/i2c-adapter/i2c-2/2-0029/lux',              # integer lux
    'proximity': '/sys/devices/platform/gpio-switch/proximity/state',  # open|closed
    'slide': '/sys/devices/platform/gpio-switch/slide/state',      # open|closed
    'lens': '/sys/devices/platform/gpio-switch/cam_shutter/state',  # open|closed
    'battery': '/sys/class/power_supply/bq27200-0/capacity',       # percent, needs bq27x00 module
}


def _read(path):
    try:
        f = open(path, 'r')
        try:
            return f.read().strip()
        finally:
            f.close()
    except (IOError, OSError):
        return None


class EMA(object):
    def __init__(self, alpha, value=0.0):
        self.alpha = alpha
        self.value = value

    def __call__(self, x):
        self.value += self.alpha * (x - self.value)
        return self.value


class Sensors(object):
    """Polled at ~20 Hz by the agent. Keeps smoothed, derived features."""

    def __init__(self, root='', paths=None, lux_max=400.0):
        self.paths = {}
        p = paths or PATHS
        for k in p:
            self.paths[k] = root + p[k] if root else p[k]
        self.lux_max = float(lux_max)
        self.accel = None
        self.prev_mag = None
        self.var = EMA(0.15)        # variance of |a|: being handled
        self.jerk = EMA(0.3)        # sample-to-sample change: shake
        self.grav = [0.0, 0.0, -1.0]
        self.light = EMA(0.2)
        self.held_until = 0.0
        self.battery = None
        self.battery_t = -1e9
        self.flat = True

    def poll(self, t):
        out = {}
        raw = _read(self.paths['accel'])
        if raw:
            try:
                x, y, z = [float(v) / 1000.0 for v in raw.split()[:3]]
                if not (finite(x) and finite(y) and finite(z)):
                    raise ValueError('accel junk: %r' % raw)
                if abs(x) > 8 or abs(y) > 8 or abs(z) > 8:
                    raise ValueError('accel out of range: %r' % raw)  # chip is +-2 g / +-8 g
                out['accel'] = {'x': round(x, 3), 'y': round(y, 3), 'z': round(z, 3)}
                mag = math.sqrt(x * x + y * y + z * z)
                if self.prev_mag is None:
                    self.prev_mag = mag
                d = mag - self.prev_mag
                self.prev_mag = mag
                v = self.var(d * d)
                # low-pass gravity for a steady tilt
                g = self.grav
                for i, val in enumerate((x, y, z)):
                    g[i] += 0.2 * (val - g[i])
                gx, gy, gz = g
                # N900 lying face-up on a table reads about (0, 0, -1) g.
                beta = atan2deg(-gy, -gz)     # front/back
                gamma = atan2deg(gx, math.sqrt(gy * gy + gz * gz))  # left/right
                out['tilt'] = {'alpha': 0, 'beta': round(beta, 1), 'gamma': round(gamma, 1)}
                # Lying still face-up OR face-down (proximity covered by the
                # plinth) is "resting"; only handling or holding it at an
                # angle counts as held.
                self.flat = (abs(beta) < 12 or abs(beta) > 168) and abs(gamma) < 12
                shake = clamp(math.sqrt(self.jerk(abs(d))) * 2.2)
                out['shake'] = round(shake, 3)
                if v > 0.0004 or shake > 0.25:
                    self.held_until = t + 2.5
                held = t < self.held_until or not self.flat
                out['held'] = bool(held)
                out['_handling'] = clamp(math.sqrt(v) * 20.0)
            except ValueError:
                pass
        lux = _read(self.paths['lux'])
        if lux:
            try:
                l = float(lux)
                if not finite(l) or l < 0:
                    raise ValueError('lux junk')
                out['light'] = round(self.light(clamp(math.log(1 + l) / math.log(1 + self.lux_max))), 3)
            except ValueError:
                pass
        prox = _read(self.paths['proximity'])
        if prox:
            out['proximity'] = {'near': prox == 'closed'}
        slide = _read(self.paths['slide'])
        if slide:
            out['slide'] = slide == 'open'
        lens = _read(self.paths['lens'])
        if lens:
            out['_lens_open'] = lens == 'open'
        if t - self.battery_t > 30:
            self.battery_t = t
            b = _read(self.paths['battery'])
            if b:
                try:
                    bv = float(b)
                    if finite(bv):
                        self.battery = clamp(bv / 100.0)
                except ValueError:
                    pass
        if self.battery is not None:
            out['battery'] = round(self.battery, 2)
        return out


def available(root=''):
    """Which sysfs sensors exist on this device (for the startup log)."""
    found = []
    for k in PATHS:
        if os.path.exists(root + PATHS[k]):
            found.append(k)
    found.sort()
    return found
