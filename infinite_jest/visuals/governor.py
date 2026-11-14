"""Automatic quality governor: keeps the frame time under a budget on a slow
machine (a Pi 5 that also runs the language model) by stepping the picture
down a notch at a time, and back up when there is room again.

The steps, cheapest last (each keeps everything the previous one turned down):
  0  full quality
  1  fewer brush strokes, 3 smear taps instead of 4
  2  smooth_scale off (the final upscale is nearest-neighbour)
  3  internal picture 480x270 (only if it was bigger)

It looks at the median render time over the last ~3 s. Over budget: one step
down. Comfortably under (below 65% of the budget) for `up_s` seconds: one step
back up. Never two changes within `hold_s` (10 s); a step up that has to be
undone within a minute doubles the wait before the next try (up to 10 min), so
it cannot see-saw. Every change is logged (stderr and `log`).

Config (visuals config keys):
  frame_budget_ms   default 28 (the Pi target, ~30 fps with headroom); 0 turns it off
"""
import sys
from collections import deque

LEVELS = (
    dict(taps=4, strokes=1.0, smooth=True, small=False),
    dict(taps=3, strokes=0.55, smooth=True, small=False),
    dict(taps=3, strokes=0.55, smooth=False, small=False),
    dict(taps=3, strokes=0.55, smooth=False, small=True),
)
NAMES = ("full", "fewer strokes and smear taps", "smooth_scale off", "internal 480x270")


class Governor:
    def __init__(self, budget_ms=28.0, smooth=True, can_shrink=True, window=90, hold_s=10.0, up_s=30.0,
                 up_ratio=0.65, quiet=False):
        self.budget = float(budget_ms or 0.0)
        self.enabled = self.budget > 0
        self.window = int(window)
        self.hold_s = float(hold_s)
        self.up_s0 = self.up_s = float(up_s)
        self.up_ratio = float(up_ratio)
        self.quiet = quiet
        # the levels that actually change something with this config
        self.levels = [0, 1]
        if smooth:
            self.levels.append(2)
        if can_shrink:
            self.levels.append(3)
        self.i = 0                       # index into self.levels
        self.samples = deque(maxlen=self.window)
        self.last_change = -1e9
        self.last_up = -1e9
        self.under_since = None
        self.log = []
        self.changes = 0

    @property
    def level(self):
        return self.levels[self.i]

    @property
    def settings(self):
        return LEVELS[self.level]

    def median(self):
        if not self.samples:
            return 0.0
        xs = sorted(self.samples)
        return xs[len(xs) // 2]

    def observe(self, ms, now):
        """One frame's render time (ms) at show time now (s). Returns the new
        level when it changes, else None."""
        if not self.enabled:
            return None
        self.samples.append(float(ms))
        if len(self.samples) < self.window // 2 or now - self.last_change < self.hold_s:
            return None
        med = self.median()
        if med > self.budget and self.i < len(self.levels) - 1:
            if now - self.last_up < 60.0:
                self.up_s = min(600.0, self.up_s * 2)    # the last step up did not hold
            return self._set(self.i + 1, now, med, "over")
        if med < self.budget * self.up_ratio and self.i > 0:
            if self.under_since is None:
                self.under_since = now
            elif now - self.under_since >= self.up_s:
                self.last_up = now
                return self._set(self.i - 1, now, med, "under")
        else:
            self.under_since = None
            if now - self.last_up > 600.0:
                self.up_s = self.up_s0                     # long stable: try again sooner next time
        return None

    def _set(self, i, now, med, why):
        old = self.level
        self.i = i
        self.last_change = now
        self.under_since = None
        self.samples.clear()
        self.changes += 1
        msg = "t=%.0fs median %.1f ms %s budget %.0f ms: quality %d -> %d (%s)" % (
            now, med, why, self.budget, old, self.level, NAMES[self.level])
        self.log.append(msg)
        if len(self.log) > 200:
            del self.log[0]
        if not self.quiet:
            print("visuals: " + msg, file=sys.stderr)
        return self.level
