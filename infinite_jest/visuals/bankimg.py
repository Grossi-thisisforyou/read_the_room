"""The overnight image library, as the renderer uses it.

bank_gen/ paints square originals into bank/<hook>/ and post-processes them
into bank/<hook>/derived/<name>.<variant>.png with JSON sidecars:
  wide    a 16:9 crop               -> faint underpainting in the ground
  poster  the crop in 5 palette colours  (preferred: it already matches)
  mono    the crop in grey
  cutout  the figure keyed out (RGBA)    -> collage figures, stand-ins

Sidecar tags (palette, composition, motifs) are optional: a missing or broken
sidecar just means "no tags". Nothing here ever raises: an unreadable file is
skipped. RAM stays bounded: per hook at most `max_per_hook` underpaintings
(the newest half plus a random sample of the rest) and half as many cutouts.
Squares are never stretched to 16:9; they are cropped to fill.
"""
import json
import os
import random
import threading
import time

import pygame

HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")
EXT = (".png", ".jpg", ".jpeg")
VARIANTS = ("wide", "mono", "poster", "cutout")
PREFER = {"poster": 3, "wide": 2, "mono": 1, None: 0}


def _split(fn):
    stem = os.path.splitext(fn)[0]
    base, dot, var = stem.rpartition(".")
    if dot and var in VARIANTS:
        return base, var
    return stem, None


def _tags(path):
    try:
        with open(os.path.splitext(path)[0] + ".json") as f:
            d = json.load(f)
        t = d.get("tags") if isinstance(d, dict) else None
        return t if isinstance(t, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _list(d):
    try:
        return sorted(n for n in os.listdir(d) if n.lower().endswith(EXT) and not n.startswith("."))
    except OSError:
        return []


def _sample(items, n, rng):
    """Newest half (names sort by time) plus a random sample of the rest."""
    if len(items) <= n:
        return list(items)
    half = n // 2
    newest = items[-half:] if half else []
    older = items[:-half] if half else list(items)
    return newest + rng.sample(older, min(len(older), n - len(newest)))


def crop_fill(img, size):
    """Scale to cover `size` and crop the middle: never stretch."""
    w, h = img.get_size()
    tw, th = size
    k = max(tw / max(1, w), th / max(1, h))
    sw, sh = max(tw, int(w * k + 0.5)), max(th, int(h * k + 0.5))
    s = pygame.transform.smoothscale(img, (sw, sh))
    return s.subsurface(((sw - tw) // 2, (sh - th) // 2, tw, th)).copy()


class Bank:
    """`cache` (optional, {path: (mtime, size, fitted surface, tags)}) lets a
    reload reuse what an earlier one read: only new or changed files are read
    and decoded. `pause` (seconds) is slept after each file read, so a
    background reload leaves the CPU to the frame loop."""

    def __init__(self, path, ground_size, max_per_hook=40, fig_h=360, seed=None, cache=None, pause=0.0):
        self.under = {}   # hook -> [(surface, tags)]
        self.cuts = {}    # hook -> [(surface, tags)]
        self.size = tuple(ground_size)
        self.cache = {}   # what this bank holds, by path (pass it to the next reload)
        self.read = 0     # files actually read and decoded by this load
        self._old = cache if cache is not None else {}
        self._pause = float(pause)
        rng = random.Random(seed)
        if not path or not os.path.isdir(path):
            return
        for hook in HOOKS:
            d = os.path.join(path, hook)
            dd = os.path.join(d, "derived")
            by_base = {}
            for folder in (d, dd):
                for fn in _list(folder):
                    base, var = _split(fn)
                    by_base.setdefault(base, {})[var] = os.path.join(folder, fn)
            bases = sorted(by_base)
            # one underpainting per original: the best variant it has
            under = []
            for b in bases:
                v = by_base[b]
                best = max((k for k in v if k != "cutout"), key=lambda k: PREFER.get(k, 0), default=None)
                if best is not None or None in v:
                    under.append(v.get(best) or v.get(None))
            cuts = [by_base[b]["cutout"] for b in bases if "cutout" in by_base[b]]
            self.under[hook] = self._load(_sample(under, max_per_hook, rng), lambda im: crop_fill(im, self.size),
                                          ("u",) + self.size)
            self.cuts[hook] = self._load(_sample(cuts, max(1, max_per_hook // 2), rng),
                                         lambda im: self._fit_h(im, fig_h), ("c", fig_h), alpha=True)
        self._old = None

    @staticmethod
    def _fit_h(im, h):
        w0, h0 = im.get_size()
        if h0 <= h:
            return im
        return pygame.transform.smoothscale(im, (max(1, int(w0 * h / h0)), h))

    def _load(self, paths, fit, how, alpha=False):
        out = []
        for p in paths:
            try:
                mt = os.path.getmtime(p)
                hit = self._old.get(p)
                if hit is not None and hit[0] == mt and hit[1] == how:
                    surf, tags = hit[2], hit[3]
                else:
                    self.read += 1
                    im = pygame.image.load(p)
                    if self._pause:
                        time.sleep(self._pause)
                    if alpha and not (im.get_flags() & pygame.SRCALPHA):
                        continue  # a cutout without transparency would be a rectangle
                    surf, tags = fit(im), _tags(p)
                    if self._pause:
                        time.sleep(self._pause)
                self.cache[p] = (mt, how, surf, tags)
                out.append((surf, tags))
            except Exception:
                pass
        return out

    def pick(self, kind, hook, palette_name, rng):
        """An image for this hook, preferring ones painted in this palette."""
        pool = (self.under if kind == "under" else self.cuts).get(hook) or []
        if not pool:
            return None
        match = [s for s, t in pool if palette_name and t.get("palette") == palette_name]
        return rng.choice(match or [s for s, _ in pool])

    def any_cut(self, rng):
        pool = [s for v in self.cuts.values() for s, _ in v]
        return rng.choice(pool) if pool else None

    def __bool__(self):
        return any(self.under.values()) or any(self.cuts.values())


class Loader:
    """Reload the bank on a background thread and hand the new Bank over.

    Reading and decoding 200 images on the frame thread froze the picture for
    ~2 s on x86 (about 5 s on a Pi). Here the thread does the file IO, decode
    and scaling (pygame releases the GIL inside them), reuses every image the
    current bank already holds, and pauses between files. The frame loop only
    calls poll() (cheap) and swaps the finished Bank in at once.
    """

    def __init__(self):
        self._thread = None
        self._result = None
        self._lock = threading.Lock()

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, path, ground_size, max_per_hook, fig_h, cache, pause=0.004):
        if self.busy:
            return False

        def run():
            try:   # lowest CPU priority for this thread only (Linux: per-thread nice)
                os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 15)
            except (AttributeError, OSError, ValueError):
                pass
            try:
                bank = Bank(path, ground_size, max_per_hook, fig_h=fig_h, cache=dict(cache), pause=pause)
            except Exception:
                bank = None
            with self._lock:
                self._result = bank
        self._thread = threading.Thread(target=run, name="ij-bank-load", daemon=True)
        self._thread.start()
        return True

    def poll(self):
        """The finished Bank, once, or None."""
        if self._result is None:
            return None
        with self._lock:
            bank, self._result = self._result, None
        return bank

    def wait(self, timeout=30.0):
        if self._thread is not None:
            self._thread.join(timeout)
        return self.poll()
