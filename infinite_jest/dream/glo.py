#!/usr/bin/env python3
"""Keep training a decoder without its encoder, and find "anchors" for the Pi to dream between.

Each training picture gets its own learnable point z; the decoder and the points
are trained together (generative latent optimisation). With --freeze only the
points move: that finds where a finished decoder keeps its pictures.

    python3 glo.py face --init models/face --data DIR --minutes 15 --out models --steps-from 1000
    python3 glo.py wall --init models/wall --data DIR --freeze --minutes 3 --out models

Writes <name>.npz/.json with "anchors": a list of points that decode to real-looking
pictures. net.py walks from anchor to anchor, so the stream stays on the pictures.
"""
import argparse
import glob
import json
import os
import random
import time

import numpy as np
import torch

import train


def load_into(dec, path):
    with np.load(path + ".npz") as z:
        dec.load_state_dict({k: torch.from_numpy(z[k].astype(np.float32)) for k in z.files})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=train.SPECS)
    ap.add_argument("--init")
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--n", type=int, default=0, help="number of training pictures (default: 600 face, 256 wall)")
    ap.add_argument("--steps-from", type=int, default=0)
    ap.add_argument("--anchors", type=int, default=48)
    ap.add_argument("--batch", type=int, default=16)
    a = ap.parse_args()
    torch.set_num_threads(int(os.environ.get("THREADS", os.cpu_count() or 4)))
    random.seed(2)
    torch.manual_seed(2)
    spec = train.SPECS[a.kind]
    name = a.name or a.kind
    os.makedirs(a.out, exist_ok=True)
    paths = sorted(glob.glob(os.path.join(a.data, "*.png")) + glob.glob(os.path.join(a.data, "*.jpg")))
    n = a.n or (600 if a.kind == "face" else 256)
    sampler = train.wall_samples if a.kind == "wall" else train.face_samples
    data = torch.from_numpy(sampler(paths, spec["size"], n))
    dec = train.Decoder(spec)
    if a.init:
        load_into(dec, a.init)
    z = torch.nn.Parameter(torch.randn(n, spec["latent"]) * 0.3)
    params = [{"params": [z], "lr": 3e-2}]
    if not a.freeze:
        params.append({"params": dec.parameters(), "lr": 2e-4})
    else:
        for p in dec.parameters():
            p.requires_grad_(False)
    opt = torch.optim.Adam(params)
    gx = lambda t: t[..., :, 1:] - t[..., :, :-1]
    gy = lambda t: t[..., 1:, :] - t[..., :-1, :]
    snaps = {50, 120, 250, 450, 700, 1000, 1400, 2000, 2800, 4000}
    sdir = os.path.join(a.out, name + "_steps")
    files = []
    if a.kind == "face" and not a.freeze:
        os.makedirs(sdir, exist_ok=True)
        idx = os.path.join(sdir, "index.json")
        if os.path.exists(idx):
            files = json.load(open(idx)).get("steps", [])
    t0 = time.time()
    step = 0
    while time.time() - t0 < a.minutes * 60:
        i = torch.randint(0, n, (a.batch,))
        y = dec(z[i])
        x = data[i]
        loss = (y - x).abs().mean() + 1.5 * ((gx(y) - gx(x)).abs().mean() + (gy(y) - gy(x)).abs().mean())
        loss = loss + 1e-3 * (z[i] ** 2).mean()          # keep the points near the middle
        opt.zero_grad()
        loss.backward()
        opt.step()
        step += 1
        if step % 100 == 0:
            print("step %d  %.1f min  loss %.4f" % (step, (time.time() - t0) / 60, loss.item()), flush=True)
        if a.kind == "face" and not a.freeze and step in snaps:
            p = os.path.join(sdir, "%05d" % (a.steps_from + step))
            train.export(dec, spec, p, {"step": a.steps_from + step})
            files.append(os.path.basename(p))
    zz = z.detach()
    pick = torch.randperm(n)[: a.anchors]
    extra = {"step": a.steps_from + (0 if a.freeze else step), "anchors": zz[pick].tolist(),
             "z_mean": zz.mean(0).tolist(), "z_std": zz.std(0).tolist()}
    train.export(dec, spec, os.path.join(a.out, name), extra)
    if a.kind == "face" and not a.freeze:
        p = os.path.join(sdir, "%05d" % (a.steps_from + step))
        train.export(dec, spec, p, extra)
        files.append(os.path.basename(p))
        json.dump({"steps": files, **extra}, open(os.path.join(sdir, "index.json"), "w"))
    print("done", step, "loss %.4f" % loss.item(), flush=True)


if __name__ == "__main__":
    main()
