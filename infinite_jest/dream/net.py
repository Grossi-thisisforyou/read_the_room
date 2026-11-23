"""The dreaming network, run live on the Pi with numpy only (no torch, no internet).

A decoder: a point z in a small number space -> one picture. Its weights come
from train.py (<name>.npz + <name>.json). About 0.3 GFLOP per wall frame, which
a Pi 5 does in a few tens of milliseconds with numpy's BLAS.
"""
from __future__ import annotations

import json
import os

import numpy as np


def _leaky(x):
    return np.maximum(x, 0.2 * x, out=x)


def _conv3(x, w, b):
    """3x3 conv, padding 1. x (C,H,W) float32, w (O,C,3,3)."""
    c, h, wd = x.shape
    p = np.pad(x, ((0, 0), (1, 1), (1, 1)))
    cols = np.empty((c, 3, 3, h, wd), np.float32)
    for dy in range(3):
        for dx in range(3):
            cols[:, dy, dx] = p[:, dy:dy + h, dx:dx + wd]
    y = w.reshape(w.shape[0], -1) @ cols.reshape(c * 9, h * wd)
    y += b[:, None]
    return y.reshape(w.shape[0], h, wd)


def _up2(x):
    return x.repeat(2, axis=1).repeat(2, axis=2)


class Decoder:
    def __init__(self, weights: dict, meta: dict):
        self.meta = meta
        self.latent = int(meta["latent"])
        self.base = (int(meta["chans"][0]), int(meta["base"][0]), int(meta["base"][1]))
        self.n_conv = len(meta["chans"]) - 1
        self.w = {k: np.ascontiguousarray(v, dtype=np.float32) for k, v in weights.items()}
        zs = meta.get("z_std")
        self.z_mean = np.asarray(meta.get("z_mean") or np.zeros(self.latent), np.float32)
        self.z_std = np.asarray(zs if zs else np.ones(self.latent), np.float32)

    @classmethod
    def load(cls, path: str) -> "Decoder":
        """path without extension: <path>.npz and <path>.json."""
        with open(path + ".json") as f:
            meta = json.load(f)
        with np.load(path + ".npz") as z:
            weights = {k: z[k] for k in z.files}
        return cls(weights, meta)

    def blend(self, other: "Decoder", t: float) -> "Decoder":
        """Weights part way from self to other (used to grow the face)."""
        t = float(min(1.0, max(0.0, t)))
        w = {k: self.w[k] * (1 - t) + other.w[k] * t for k in self.w}
        return Decoder(w, other.meta if t > 0.5 else self.meta)

    def __call__(self, z: np.ndarray) -> np.ndarray:
        """z (latent,) -> image (H, W, 3) uint8."""
        w = self.w
        x = w["fc.weight"] @ z.astype(np.float32) + w["fc.bias"]
        x = _leaky(x).reshape(self.base)
        for i in range(self.n_conv):
            x = _leaky(_conv3(_up2(x), w["convs.%d.weight" % i], w["convs.%d.bias" % i]))
        x = _conv3(x, w["out.weight"], w["out.bias"])
        x = 1.0 / (1.0 + np.exp(-x))
        return (x.transpose(1, 2, 0) * 255.0).astype(np.uint8)


def find(models_dir: str, name: str) -> str | None:
    p = os.path.join(models_dir, name)
    return p if os.path.exists(p + ".npz") and os.path.exists(p + ".json") else None
