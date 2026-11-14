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
    def __init__(self, path, ground_size, max_per_hook=40, fig_h=360, seed=None):
        self.under = {}   # hook -> [(surface, tags)]
        self.cuts = {}    # hook -> [(surface, tags)]
        self.size = tuple(ground_size)
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
            self.under[hook] = self._load(_sample(under, max_per_hook, rng), lambda im: crop_fill(im, self.size))
            self.cuts[hook] = self._load(_sample(cuts, max(1, max_per_hook // 2), rng),
                                         lambda im: self._fit_h(im, fig_h), alpha=True)

    @staticmethod
    def _fit_h(im, h):
        w0, h0 = im.get_size()
        if h0 <= h:
            return im
        return pygame.transform.smoothscale(im, (max(1, int(w0 * h / h0)), h))

    @staticmethod
    def _load(paths, fit, alpha=False):
        out = []
        for p in paths:
            try:
                im = pygame.image.load(p)
                if alpha and not (im.get_flags() & pygame.SRCALPHA):
                    continue  # a cutout without transparency would be a rectangle
                out.append((fit(im), _tags(p)))
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
