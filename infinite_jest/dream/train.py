#!/usr/bin/env python3
"""Train the two small dreaming networks the Pi runs live (not run on the Pi).

    python3 train.py wall  --data DIR --minutes 40 --out ../dream/models
    python3 train.py face  --data DIR --minutes 15 --out ../dream/models

Both are small variational autoencoders. Only the decoder goes to the Pi: it
turns a point in a 64- (wall) or 32- (face) number space into a picture, and the
Pi walks that space live, so the stream is new every time.

wall: learns the show's own painted look (frames of our earlier visuals) -> 160x96.
face: learns one guest's face from their guest-file photos -> 128x128. Snapshots
      are saved along the way: the earliest is a grey, featureless head, the last
      is the guest. The Pi blends from snapshot to snapshot while the visitor stays.

Needs torch (CPU is fine). Writes <name>.npz + <name>.json (see dream/net.py).
"""
import argparse
import glob
import json
import math
import os
import random
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image, ImageEnhance, ImageFilter

SPECS = {
    "wall": {"latent": 64, "base": [3, 5], "chans": [256, 192, 128, 64, 32, 16], "size": [96, 160]},
    "face": {"latent": 32, "base": [4, 4], "chans": [256, 192, 128, 64, 32, 16], "size": [128, 128]},
}


class Decoder(nn.Module):
    def __init__(self, spec):
        super().__init__()
        c = spec["chans"]
        h, w = spec["base"]
        self.base = (c[0], h, w)
        self.fc = nn.Linear(spec["latent"], c[0] * h * w)
        self.convs = nn.ModuleList(nn.Conv2d(c[i], c[i + 1], 3, padding=1) for i in range(len(c) - 1))
        self.out = nn.Conv2d(c[-1], 3, 3, padding=1)

    def forward(self, z):
        x = F.leaky_relu(self.fc(z), 0.2).view(-1, *self.base)
        for conv in self.convs:
            x = F.leaky_relu(conv(F.interpolate(x, scale_factor=2, mode="nearest")), 0.2)
        return torch.sigmoid(self.out(x))


class Encoder(nn.Module):
    def __init__(self, spec):
        super().__init__()
        c = [3] + list(reversed(spec["chans"]))[1:]       # 3,32,64,128,192,256
        layers = []
        for i in range(len(c) - 1):
            layers += [nn.Conv2d(c[i], c[i + 1], 4, 2, 1), nn.BatchNorm2d(c[i + 1]), nn.LeakyReLU(0.2)]
        self.net = nn.Sequential(*layers)
        h, w = spec["base"]
        self.mu = nn.Linear(c[-1] * h * w, spec["latent"])
        self.lv = nn.Linear(c[-1] * h * w, spec["latent"])

    def forward(self, x):
        y = self.net(x).flatten(1)
        return self.mu(y), self.lv(y).clamp(-8, 8)


# ------------------------------------------------------------------ data
def wall_samples(paths, size, n):
    H, W = size
    out = np.zeros((n, 3, H, W), np.float32)
    imgs = [Image.open(p).convert("RGB") for p in paths]
    for i in range(n):
        im = random.choice(imgs)
        s = random.uniform(0.55, 1.0)                 # random 16:10 window of the frame
        cw, ch = int(im.width * s), int(im.width * s * H / W)
        ch = min(ch, im.height)
        x0, y0 = random.randint(0, im.width - cw), random.randint(0, im.height - ch)
        crop = im.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BILINEAR)
        if random.random() < 0.5:
            crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
        out[i] = np.asarray(crop, np.float32).transpose(2, 0, 1) / 255.0
    return out


def face_samples(paths, size, n):
    H, W = size
    out = np.zeros((n, 3, H, W), np.float32)
    imgs = [Image.open(p).convert("RGB") for p in paths]
    for i in range(n):
        im = random.choice(imgs)
        ang = random.uniform(-6, 6)
        s = random.uniform(0.88, 1.0)
        r = im.rotate(ang, resample=Image.BILINEAR)
        cw = int(im.width * s)
        x0 = random.randint(0, im.width - cw)
        y0 = random.randint(0, im.height - cw)
        crop = r.crop((x0, y0, x0 + cw, y0 + cw)).resize((W, H), Image.BILINEAR)
        crop = ImageEnhance.Brightness(crop).enhance(random.uniform(0.85, 1.1))
        out[i] = np.asarray(crop, np.float32).transpose(2, 0, 1) / 255.0
    return out


# ------------------------------------------------------------------ export
def export(dec, spec, path, extra=None):
    sd = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in dec.state_dict().items()}
    np.savez_compressed(path + ".npz", **sd)
    meta = dict(spec)
    meta.update(extra or {})
    with open(path + ".json", "w") as f:
        json.dump(meta, f, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=SPECS)
    ap.add_argument("--data", required=True)
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name")
    ap.add_argument("--beta", type=float, default=None)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--edge", type=float, default=1.0)
    a = ap.parse_args()
    torch.set_num_threads(int(os.environ.get("THREADS", os.cpu_count() or 4)))
    random.seed(1)
    torch.manual_seed(1)
    spec = SPECS[a.kind]
    name = a.name or a.kind
    os.makedirs(a.out, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(a.data, "*.png")) + glob.glob(os.path.join(a.data, "*.jpg")))
    sampler = wall_samples if a.kind == "wall" else face_samples
    pool_n = 4000 if a.kind == "wall" else 1500
    print("images", len(paths), "-> making", pool_n, "training crops", flush=True)
    pool = torch.from_numpy(sampler(paths, spec["size"], pool_n))
    enc, dec = Encoder(spec), Decoder(spec)
    opt = torch.optim.Adam(list(enc.parameters()) + list(dec.parameters()), lr=3e-4)
    beta = a.beta if a.beta is not None else (0.002 if a.kind == "wall" else 0.0005)
    npix = 3 * spec["size"][0] * spec["size"][1]
    snaps = [25, 50, 90, 150, 250, 400, 650, 1000, 1600, 2500, 4000, 6000]
    snap_files = []
    if a.kind == "face":
        os.makedirs(os.path.join(a.out, name + "_steps"), exist_ok=True)
    t0 = time.time()
    step = 0
    refresh = 0
    while time.time() - t0 < a.minutes * 60:
        idx = torch.randint(0, len(pool), (a.batch,))
        x = pool[idx]
        mu, lv = enc(x)
        z = mu + torch.randn_like(mu) * torch.exp(0.5 * lv)
        y = dec(z)
        rec = (y - x).abs().mean() + 0.5 * ((y - x) ** 2).mean()
        # edges count double: plain pixel losses make a blurry average
        gx = lambda t: t[..., :, 1:] - t[..., :, :-1]
        gy = lambda t: t[..., 1:, :] - t[..., :-1, :]
        rec = rec + a.edge * ((gx(y) - gx(x)).abs().mean() + (gy(y) - gy(x)).abs().mean())
        kl = (-0.5 * (1 + lv - mu ** 2 - lv.exp()).sum(1).mean()) / npix
        loss = rec + beta * kl * npix / 100.0
        opt.zero_grad()
        loss.backward()
        opt.step()
        step += 1
        if a.kind == "face" and step in snaps:
            p = os.path.join(a.out, name + "_steps", "%05d" % step)
            export(dec, spec, p, {"step": step})
            snap_files.append(os.path.basename(p))
        if step % 200 == 0:
            print("step %d  %.1f min  rec %.4f  kl %.3f" % (step, (time.time() - t0) / 60, rec.item(), kl.item() * npix),
                  flush=True)
            export(dec, spec, os.path.join(a.out, name), {"step": step})
        if a.kind == "wall" and step % 1500 == 0:             # fresh crops now and then
            refresh += 1
            pool = torch.from_numpy(sampler(paths, spec["size"], pool_n))
    # latent statistics, so the Pi walks where the pictures are
    with torch.no_grad():
        mus = torch.cat([enc(pool[i:i + 64])[0] for i in range(0, min(len(pool), 1024), 64)])
    extra = {"step": step, "z_mean": mus.mean(0).tolist(), "z_std": mus.std(0).tolist()}
    export(dec, spec, os.path.join(a.out, name), extra)
    if a.kind == "face":
        p = os.path.join(a.out, name + "_steps", "%05d" % step)
        export(dec, spec, p, extra)
        snap_files.append(os.path.basename(p))
        with open(os.path.join(a.out, name + "_steps", "index.json"), "w") as f:
            json.dump({"steps": snap_files, **extra}, f)
    print("done", step, "steps", flush=True)


if __name__ == "__main__":
    main()
