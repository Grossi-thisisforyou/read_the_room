"""Shared file conventions for the image bank. Python standard library only.

    bank/<hook>/<name>.png            an original painted image (what the renderer reads)
    bank/<hook>/<name>.json           its sidecar: prompt, seed, tags ...
    bank/<hook>/derived/<name>.<variant>.png  + .json
                                      post-processed versions (postprocess.py)
    bank/.incoming/                   half-made images (generate.py)
    bank/.trash/<batch>/              images removed by curate.py (undoable)

<name> is "<YYYYmmdd-HHMMSS>_<seed>" for generated images, but any name works:
hand-added paintings are fine too.
"""
import json
import os
import time

HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")
IMAGE_EXT = (".png", ".jpg", ".jpeg")
DERIVED_DIR = "derived"
VARIANTS = ("wide", "mono", "poster", "cutout")


def is_image(fn):
    return fn.lower().endswith(IMAGE_EXT) and not fn.startswith(".")


def sidecar_path(image_path):
    return os.path.splitext(image_path)[0] + ".json"


def read_sidecar(image_path):
    try:
        with open(sidecar_path(image_path)) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json_atomic(path, data):
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def split_variant(fn):
    """'x.wide.png' -> ('x', 'wide'); 'x.png' -> ('x', None)."""
    stem = os.path.splitext(fn)[0]
    base, dot, var = stem.rpartition(".")
    if dot and var in VARIANTS:
        return base, var
    return stem, None


def list_images(d):
    try:
        names = os.listdir(d)
    except OSError:
        return []
    return sorted(os.path.join(d, n) for n in names
                  if is_image(n) and os.path.isfile(os.path.join(d, n)))


def sources(hook_dir):
    """Original images of a hook: top-level images that aren't variants, plus
    originals that postprocess --wide-to-hook moved into derived/."""
    out = [p for p in list_images(hook_dir) if split_variant(os.path.basename(p))[1] is None]
    ddir = os.path.join(hook_dir, DERIVED_DIR)
    for p in list_images(ddir):
        if split_variant(os.path.basename(p))[1] is None:
            out.append(p)
    return out


def derived_files(hook_dir, base):
    """Every derived file (images and sidecars) made from original <base>."""
    out = []
    for d in (hook_dir, os.path.join(hook_dir, DERIVED_DIR)):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            b, var = split_variant(n)   # matches x.wide.png and x.wide.json alike
            if var and b == base and os.path.isfile(os.path.join(d, n)):
                out.append(os.path.join(d, n))
    return sorted(out)


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
