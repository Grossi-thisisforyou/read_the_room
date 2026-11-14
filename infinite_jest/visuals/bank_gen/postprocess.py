#!/usr/bin/env python3
"""Turn painted bank images into renderer-friendly versions.

For every original image in bank/<hook>/ it makes, in bank/<hook>/derived/:

    <name>.wide.png    16:9 crop, scaled to 1280x720 (no stretching on the projector)
    <name>.mono.png    the wide crop in greys
    <name>.poster.png  the wide crop posterized into the 5 colours of its palette
                       (the palette named in its tags, from visuals/palettes.py)
    <name>.cutout.png  the figure cut out of a flat ground, with transparency,
                       cropped to the figure. Skipped when the ground isn't flat
                       enough to cut cleanly (the sidecar of the original says why).

Each one gets a .json sidecar with the original's prompt and tags plus
"variant:<name>", so the renderer can pick by tag later.

    python3 postprocess.py                 # everything not done yet
    python3 postprocess.py --hook flesh    # one hook
    python3 postprocess.py --prune         # also remove versions whose original is gone
    python3 postprocess.py --wide-to-hook  # see README: makes today's renderer use 16:9

Works with Pillow (fast, any PNG or JPEG) and without it (pure Python: slow,
PNG only, a few seconds per image). Never stops on a bad file: it says what
went wrong and carries on.
"""
import argparse
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bankfiles  # noqa: E402
import pngio  # noqa: E402

try:  # the renderer's palettes, read-only
    sys.path.insert(0, os.path.dirname(HERE))
    import palettes as _palettes  # noqa: E402
    NAMED_PALETTES = {k: [_palettes.hex2rgb(c) for c in v] for k, v in _palettes.NAMED.items()}
    HOOK_DEFAULT_PALETTE = dict(_palettes.HOOK_DEFAULT)
except Exception:  # pragma: no cover - visuals/ not next to us
    NAMED_PALETTES = {"ash": [(0, 0, 0), (21, 21, 21), (61, 61, 61), (138, 138, 138), (224, 224, 224)]}
    HOOK_DEFAULT_PALETTE = {}
finally:
    sys.path.pop(0)

DEFAULT_SIZE = (1280, 720)
ALL_VARIANTS = bankfiles.VARIANTS

# cut-out settings (0-255 colour units)
KEY_LOW = 28        # closer than this to the ground colour: fully transparent
KEY_HIGH = 64       # further than this: fully opaque; in between: soft edge
FLAT_SHARE = 0.6    # this share of the border must be ground-coloured to try
MIN_COVER, MAX_COVER = 0.02, 0.85   # figure must cover 2-85% of the picture
MARGIN = 0.04       # space left around the cropped figure

# where to crop vertically for 16:9 (0 = keep the top, 0.5 = middle)
CROP_BIAS = {"bust": 0.3, "close-up": 0.35, "full-body": 0.4}


def log(msg):
    print("%s  %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


# ------------------------------------------------------------------ shared maths

def crop_box(w, h, aspect=16 / 9, bias=0.5):
    """Largest box of the given aspect inside w x h, as (x, y, cw, ch)."""
    if w / h > aspect:
        cw = int(round(h * aspect))
        return ((w - cw) // 2, 0, cw, h)
    ch = int(round(w / aspect))
    return (0, int(round((h - ch) * bias)), w, ch)


def median(values):
    v = sorted(values)
    return v[len(v) // 2] if v else 0


def ground_from_border(samples):
    """samples: list of (r, g, b). Returns (ground colour, flat share)."""
    g = tuple(median([s[i] for s in samples]) for i in range(3))
    close = sum(1 for s in samples if max(abs(s[0] - g[0]), abs(s[1] - g[1]), abs(s[2] - g[2])) < KEY_LOW)
    return g, close / max(1, len(samples))


def key_lut(low=KEY_LOW, high=KEY_HIGH):
    return bytes(0 if v <= low else 255 if v >= high else int(255 * (v - low) / (high - low))
                 for v in range(256))


def stretch_range(hist, cut=0.01):
    """Darkest and lightest luminance after ignoring the extreme 1% each side."""
    total = sum(hist)
    if not total:
        return 0, 255
    lo_n, hi_n = total * cut, total * (1 - cut)
    acc, lo, hi = 0, 0, 255
    for v, n in enumerate(hist):
        if acc <= lo_n < acc + n:
            lo = v
        if acc < hi_n <= acc + n:
            hi = v
        acc += n
    return (lo, hi) if hi > lo else (0, 255)


def poster_lut(colors, lo=0, hi=255):
    """Luminance 0-255 -> one of the palette's 5 colours (dark to light),
    after stretching lo..hi to the full range so a figure and a ground of
    similar brightness still land in different bands."""
    n = len(colors)
    span = max(1, hi - lo)
    idx = [min(n - 1, max(0, (v - lo) * n // (span + 1))) for v in range(256)]
    return [bytes(colors[i][c] for i in idx) for c in range(3)]


def palette_for(meta, hook):
    tags = meta.get("tags") if isinstance(meta.get("tags"), dict) else {}
    name = tags.get("palette") or HOOK_DEFAULT_PALETTE.get(hook) or "ash"
    if name not in NAMED_PALETTES:
        name = HOOK_DEFAULT_PALETTE.get(hook, "ash")
    return name, NAMED_PALETTES.get(name) or NAMED_PALETTES["ash"]


# ------------------------------------------------------------------ engines

class PureEngine:
    """Standard library only. PNG in, PNG out."""
    name = "pure-python"

    def load(self, path):
        if not path.lower().endswith(".png"):
            raise ValueError("JPEG needs Pillow (sudo apt install python3-pil)")
        img = pngio.read(path)
        if img.channels == 4:  # drop alpha
            d = img.data
            rgb = bytearray(img.w * img.h * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = d[0::4], d[1::4], d[2::4]
            img = pngio.Raw(img.w, img.h, 3, rgb)
        return img

    @staticmethod
    def size(img):
        return img.w, img.h

    def save(self, img, path):
        pngio.write(path, img)

    def crop_resize(self, img, box, out_w, out_h):
        x0, y0, cw, ch = box
        src, sw = img.data, img.w
        # horizontal pass on the cropped rows
        xs = [x0 + (i + 0.5) * cw / out_w - 0.5 for i in range(out_w)]
        i0, i1, fx = [], [], []
        for x in xs:
            x = min(max(x, x0), x0 + cw - 1)
            a = int(x)
            b = min(a + 1, x0 + cw - 1)
            f = x - a
            for c in range(3):
                i0.append(a * 3 + c)
                i1.append(b * 3 + c)
                fx.append(f)
        rows = []
        for y in range(y0, y0 + ch):
            row = src[y * sw * 3:(y + 1) * sw * 3]
            rows.append([row[a] + (row[b] - row[a]) * f for a, b, f in zip(i0, i1, fx)])
        # vertical pass
        out = bytearray()
        for j in range(out_h):
            y = min(max((j + 0.5) * ch / out_h - 0.5, 0), ch - 1)
            a = int(y)
            b = min(a + 1, ch - 1)
            f = y - a
            ra, rb = rows[a], rows[b]
            out += bytes(int(p + (q - p) * f + 0.5) for p, q in zip(ra, rb))
        return pngio.Raw(out_w, out_h, 3, out)

    @staticmethod
    def _lum(img):
        d = img.data
        return bytes((299 * r + 587 * g + 114 * b + 500) // 1000
                     for r, g, b in zip(d[0::3], d[1::3], d[2::3]))

    def mono(self, img):
        lum = self._lum(img)
        out = bytearray(len(lum) * 3)
        out[0::3] = out[1::3] = out[2::3] = lum
        return pngio.Raw(img.w, img.h, 3, out)

    def poster(self, img, colors):
        lum = self._lum(img)
        lr, lg, lb = poster_lut(colors, *stretch_range([lum.count(v) for v in range(256)]))
        out = bytearray(len(lum) * 3)
        out[0::3] = lum.translate(lr)
        out[1::3] = lum.translate(lg)
        out[2::3] = lum.translate(lb)
        return pngio.Raw(img.w, img.h, 3, out)

    def border_samples(self, img, strip):
        w, h, d = img.w, img.h, img.data
        step = max(1, min(w, h) // 128)
        out = []
        for y in list(range(0, strip)) + list(range(h - strip, h)):
            for x in range(0, w, step):
                i = (y * w + x) * 3
                out.append((d[i], d[i + 1], d[i + 2]))
        for x in list(range(0, strip)) + list(range(w - strip, w)):
            for y in range(strip, h - strip, step):
                i = (y * w + x) * 3
                out.append((d[i], d[i + 1], d[i + 2]))
        return out

    def alpha_key(self, img, ground):
        d = img.data
        gr, gg, gb = ground
        lut = key_lut()
        dist = bytes(max(abs(r - gr), abs(g - gg), abs(b - gb))
                     for r, g, b in zip(d[0::3], d[1::3], d[2::3]))
        a = dist.translate(lut)
        return self._box_blur(a, img.w, img.h)

    @staticmethod
    def _box_blur(a, w, h):
        # 3x3 box blur, edges clamped; two 3-tap passes
        hor = bytearray(len(a))
        for y in range(h):
            r = a[y * w:(y + 1) * w]
            left = r[:1] + r[:-1]
            right = r[1:] + r[-1:]
            hor[y * w:(y + 1) * w] = bytes((p + q + s + 1) // 3 for p, q, s in zip(left, r, right))
        out = bytearray(len(a))
        for y in range(h):
            up = hor[max(0, y - 1) * w:max(0, y - 1) * w + w]
            mid = hor[y * w:(y + 1) * w]
            dn = hor[min(h - 1, y + 1) * w:min(h - 1, y + 1) * w + w]
            out[y * w:(y + 1) * w] = bytes((p + q + s + 1) // 3 for p, q, s in zip(up, mid, dn))
        return out

    @staticmethod
    def alpha_stats(alpha, w, h):
        cover = sum(1 for v in alpha if v >= 128) / float(w * h)
        xs, ys = [], []
        for y in range(h):
            row = alpha[y * w:(y + 1) * w]
            hits = [x for x, v in enumerate(row) if v >= 32]
            if hits:
                ys.append(y)
                xs.append(hits[0])
                xs.append(hits[-1])
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1) if xs else None
        return cover, bbox

    def compose_rgba(self, img, alpha, box):
        x0, y0, x1, y1 = box
        w = img.w
        out = bytearray()
        for y in range(y0, y1):
            rgb = img.data[(y * w + x0) * 3:(y * w + x1) * 3]
            a = alpha[y * w + x0:y * w + x1]
            row = bytearray(len(a) * 4)
            row[0::4], row[1::4], row[2::4], row[3::4] = rgb[0::3], rgb[1::3], rgb[2::3], a
            out += row
        return pngio.Raw(x1 - x0, y1 - y0, 4, out)


class PillowEngine:
    name = "pillow"

    def __init__(self):
        from PIL import Image, ImageChops, ImageFilter
        self.Image, self.Chops, self.Filter = Image, ImageChops, ImageFilter
        self.lanczos = getattr(Image, "Resampling", Image).LANCZOS

    def load(self, path):
        im = self.Image.open(path)
        im.load()
        if im.mode != "RGB":
            if "A" in im.getbands() or im.mode == "P":
                im = im.convert("RGBA")
                bg = self.Image.new("RGB", im.size, (0, 0, 0))
                bg.paste(im, mask=im.split()[3])
                im = bg
            else:
                im = im.convert("RGB")
        return im

    @staticmethod
    def size(img):
        return img.size

    def save(self, img, path):
        img.save(path, format="PNG", compress_level=6)

    def crop_resize(self, img, box, out_w, out_h):
        x, y, cw, ch = box
        return img.crop((x, y, x + cw, y + ch)).resize((out_w, out_h), self.lanczos)

    def mono(self, img):
        return img.convert("L").convert("RGB")

    def poster(self, img, colors):
        lum = img.convert("L")
        lr, lg, lb = poster_lut(colors, *stretch_range(lum.histogram()))
        return self.Image.merge("RGB", [lum.point(list(t)) for t in (lr, lg, lb)])

    def border_samples(self, img, strip):
        w, h = img.size
        step = max(1, min(w, h) // 128)
        out = []
        for box in ((0, 0, w, strip), (0, h - strip, w, h), (0, strip, strip, h - strip),
                    (w - strip, strip, w, h - strip)):
            part = img.crop(box)
            get = getattr(part, "get_flattened_data", None) or part.getdata  # Pillow 12+ / older
            px = list(get())
            out.extend(px[::step])
        return out

    def alpha_key(self, img, ground):
        solid = self.Image.new("RGB", img.size, tuple(ground))
        r, g, b = self.Chops.difference(img, solid).split()
        dist = self.Chops.lighter(self.Chops.lighter(r, g), b)
        return dist.point(list(key_lut())).filter(self.Filter.BoxBlur(1))

    @staticmethod
    def alpha_stats(alpha, w, h):
        hist = alpha.histogram()
        cover = sum(hist[128:]) / float(w * h)
        bbox = alpha.point(lambda v: 255 if v >= 32 else 0).getbbox()
        return cover, bbox

    def compose_rgba(self, img, alpha, box):
        rgba = img.convert("RGBA")
        rgba.putalpha(alpha)
        return rgba.crop(box)


def pick_engine(choice="auto"):
    if choice in ("auto", "pillow"):
        try:
            return PillowEngine()
        except ImportError:
            if choice == "pillow":
                raise SystemExit("Pillow is not installed (sudo apt install python3-pil, or pip install pillow)")
    return PureEngine()


# ------------------------------------------------------------------ one image

def make_cutout(engine, img):
    """Returns (rgba image or None, info dict)."""
    w, h = engine.size(img)
    strip = max(2, min(w, h) // 50)
    ground, flat = ground_from_border(engine.border_samples(img, strip))
    info = {"ground": list(ground), "flat_border": round(flat, 3)}
    if flat < FLAT_SHARE:
        info["skipped"] = "ground not flat enough to cut out (%.0f%% of the border matches)" % (flat * 100)
        return None, info
    alpha = engine.alpha_key(img, ground)
    cover, bbox = engine.alpha_stats(alpha, w, h)
    info["coverage"] = round(cover, 3)
    if bbox is None or not (MIN_COVER <= cover <= MAX_COVER):
        info["skipped"] = "figure covers %.0f%% of the picture (want %d-%d%%)" % (
            cover * 100, MIN_COVER * 100, MAX_COVER * 100)
        return None, info
    mx, my = int(w * MARGIN), int(h * MARGIN)
    box = (max(0, bbox[0] - mx), max(0, bbox[1] - my), min(w, bbox[2] + mx), min(h, bbox[3] + my))
    info["box"] = list(box)
    info["anchor"] = [round((box[0] + box[2]) / 2 / w, 3), round(box[3] / h, 3)]  # centre x, foot y
    return engine.compose_rgba(img, alpha, box), info


class Options:
    def __init__(self, variants=ALL_VARIANTS, size=DEFAULT_SIZE, force=False,
                 wide_to_hook=False, keep_poor=False, dry_run=False, quiet=False):
        self.variants = tuple(variants)
        self.size = tuple(size)
        self.force = force
        self.wide_to_hook = wide_to_hook
        self.keep_poor = keep_poor
        self.dry_run = dry_run
        self.quiet = quiet


def out_path(hook_dir, base, variant, opts):
    if variant == "wide" and opts.wide_to_hook:
        return os.path.join(hook_dir, "%s.wide.png" % base)
    return os.path.join(hook_dir, bankfiles.DERIVED_DIR, "%s.%s.png" % (base, variant))


def _up_to_date(path, src):
    try:
        return os.path.getmtime(path) >= os.path.getmtime(src)
    except OSError:
        return False


def _save(engine, img, path, side):
    tmp = path + ".tmp.png"
    engine.save(img, tmp)
    os.replace(tmp, path)
    bankfiles.write_json_atomic(bankfiles.sidecar_path(path), side)


def process_one(src, hook, engine, opts):
    """Make the missing versions of one original. Returns {variant: status}."""
    hook_dir = os.path.dirname(src)
    in_derived = os.path.basename(hook_dir) == bankfiles.DERIVED_DIR
    if in_derived:
        hook_dir = os.path.dirname(hook_dir)
    base = os.path.splitext(os.path.basename(src))[0]
    meta = bankfiles.read_sidecar(src)
    status = {}
    if in_derived and meta.get("moved_for_wide") and not os.path.exists(
            os.path.join(hook_dir, base + ".wide.png")):
        return {"all": "retired"}   # its wide copy was deleted from the hook: leave it for --prune

    todo = []
    for v in opts.variants:
        p = out_path(hook_dir, base, v, opts)
        if not opts.force and _up_to_date(p, src):
            status[v] = "up to date"
        elif v == "cutout" and not opts.force and not opts.keep_poor \
                and meta.get("cutout_skipped_mtime") == os.path.getmtime(src):
            status[v] = "skipped before"
        else:
            todo.append(v)
    if not todo:
        return status
    if opts.dry_run:
        return dict(status, **{v: "would make" for v in todo})

    img = engine.load(src)
    w, h = engine.size(img)
    tags = dict(meta.get("tags") or {"hook": hook})
    tag_list = list(meta.get("tag_list") or ["hook:" + hook])
    framing = (tags.get("composition") or {}).get("framing") if isinstance(tags.get("composition"), dict) else None
    pal_name, pal = palette_for(meta, hook)
    rel_src = os.path.relpath(src, hook_dir)
    os.makedirs(os.path.join(hook_dir, bankfiles.DERIVED_DIR), exist_ok=True)

    def sidecar(variant, img_out, extra):
        ow, oh = engine.size(img_out)
        return {
            "hook": hook,
            "variant": variant,
            "derived_from": rel_src,
            "width": ow,
            "height": oh,
            "prompt": meta.get("prompt"),
            "seed": meta.get("seed"),
            "tags": dict(tags, variant=variant),
            "tag_list": tag_list + ["variant:" + variant],
            "postprocess": dict(extra, engine=engine.name, source_size=[w, h]),
            "created": bankfiles.now_iso(),
            "generator": "bank_gen/postprocess.py",
        }

    wide = None
    if any(v in todo for v in ("wide", "mono", "poster")):
        bias = CROP_BIAS.get(framing, 0.5)
        box = crop_box(w, h, opts.size[0] / opts.size[1], bias)
        wide = engine.crop_resize(img, box, opts.size[0], opts.size[1])
        crop_info = {"crop": list(box)}
        if "wide" in todo:
            _save(engine, wide, out_path(hook_dir, base, "wide", opts), sidecar("wide", wide, crop_info))
            status["wide"] = "made"
        if "mono" in todo:
            m = engine.mono(wide)
            _save(engine, m, out_path(hook_dir, base, "mono", opts), sidecar("mono", m, crop_info))
            status["mono"] = "made"
        if "poster" in todo:
            m = engine.poster(wide, pal)
            _save(engine, m, out_path(hook_dir, base, "poster", opts),
                  sidecar("poster", m, dict(crop_info, palette=pal_name, levels=len(pal))))
            status["poster"] = "made"
    if "cutout" in todo:
        cut, info = make_cutout(engine, img)
        if cut is None:
            status["cutout"] = "skipped: " + info["skipped"]
            meta_update = {"cutout_skipped": info["skipped"], "cutout_skipped_mtime": os.path.getmtime(src)}
            meta.update(meta_update)
            bankfiles.write_json_atomic(bankfiles.sidecar_path(src), meta)
        else:
            _save(engine, cut, out_path(hook_dir, base, "cutout", opts), sidecar("cutout", cut, info))
            status["cutout"] = "made"

    if opts.wide_to_hook and status.get("wide") == "made" and not in_derived:
        _move_original(src, hook_dir, base)
    return status


def _move_original(src, hook_dir, base):
    """--wide-to-hook: the square original moves into derived/ so the renderer
    (which reads the hook folder) only sees the 16:9 copy."""
    ddir = os.path.join(hook_dir, bankfiles.DERIVED_DIR)
    dst = os.path.join(ddir, os.path.basename(src))
    side_src = bankfiles.sidecar_path(src)
    meta = bankfiles.read_sidecar(src)
    meta["moved_for_wide"] = True
    shutil.move(src, dst)
    bankfiles.write_json_atomic(bankfiles.sidecar_path(dst), meta)
    if os.path.exists(side_src):
        os.remove(side_src)
    wide_side = os.path.join(hook_dir, base + ".wide.json")
    try:
        import json
        with open(wide_side) as f:
            ws = json.load(f)
        ws["derived_from"] = os.path.relpath(dst, hook_dir)
        bankfiles.write_json_atomic(wide_side, ws)
    except (OSError, ValueError):
        pass


# ------------------------------------------------------------------ whole bank

def prune(bank, hooks, dry_run=False):
    """Remove derived files whose original is gone. Returns the removed paths."""
    removed = []
    for hook in hooks:
        hook_dir = os.path.join(bank, hook)
        ddir = os.path.join(hook_dir, bankfiles.DERIVED_DIR)
        top_bases = {bankfiles.split_variant(os.path.basename(p))[0]
                     for p in bankfiles.list_images(hook_dir)
                     if bankfiles.split_variant(os.path.basename(p))[1] is None}
        doomed = []
        # moved originals whose wide copy was removed from the hook folder
        for p in bankfiles.list_images(ddir):
            base, var = bankfiles.split_variant(os.path.basename(p))
            if var is None and bankfiles.read_sidecar(p).get("moved_for_wide") \
                    and not os.path.exists(os.path.join(hook_dir, base + ".wide.png")):
                doomed += [p, bankfiles.sidecar_path(p)]
        alive = top_bases | {bankfiles.split_variant(os.path.basename(p))[0]
                             for p in bankfiles.list_images(ddir)
                             if bankfiles.split_variant(os.path.basename(p))[1] is None
                             and p not in doomed}
        for d in (hook_dir, ddir):
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                base, var = bankfiles.split_variant(n)
                if var and base not in alive:
                    doomed.append(os.path.join(d, n))
        for p in sorted(set(doomed)):
            if os.path.exists(p):
                removed.append(p)
                if not dry_run:
                    os.remove(p)
    return removed


def run(bank, hooks=bankfiles.HOOKS, engine=None, opts=None, limit=None, do_prune=False, out=log):
    opts = opts or Options()
    engine = engine or pick_engine()
    counts = {"made": 0, "failed": 0, "skipped": 0, "images": 0}
    if do_prune:
        gone = prune(bank, hooks, opts.dry_run)
        if gone:
            out("%s %d derived file(s) whose original is gone" % (
                "would remove" if opts.dry_run else "removed", len(gone)))
    for hook in hooks:
        for src in bankfiles.sources(os.path.join(bank, hook)):
            if limit is not None and counts["images"] >= limit:
                return counts
            try:
                st = process_one(src, hook, engine, opts)
            except Exception as e:  # fail soft: report and carry on
                counts["failed"] += 1
                out("FAILED %s: %s" % (os.path.relpath(src, bank), e))
                continue
            made = [v for v, s in st.items() if s in ("made", "would make")]
            if made:
                counts["images"] += 1
                counts["made"] += len(made)
            skipped = [s for s in st.values() if s.startswith("skipped:")]
            counts["skipped"] += len(skipped)
            if (made or skipped) and not opts.quiet:
                out("%s  %s" % (os.path.relpath(src, bank),
                                ", ".join("%s %s" % (v, s) for v, s in st.items() if s != "up to date")))
    return counts


def parse_size(text):
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("--size wants WIDTHxHEIGHT, e.g. 1280x720")


def main(argv=None):
    p = argparse.ArgumentParser(description="Make renderer-friendly versions of the bank images.")
    p.add_argument("--bank", default=os.path.normpath(os.path.join(HERE, "..", "bank")))
    p.add_argument("--hook", choices=bankfiles.HOOKS, action="append",
                   help="only this hook (repeatable; default all)")
    p.add_argument("--variants", default=",".join(ALL_VARIANTS),
                   help="comma list of %s (default: all)" % ", ".join(ALL_VARIANTS))
    p.add_argument("--size", type=parse_size, default=DEFAULT_SIZE, help="wide size (default 1280x720)")
    p.add_argument("--force", action="store_true", help="remake versions that already exist")
    p.add_argument("--prune", action="store_true", help="remove versions whose original was deleted")
    p.add_argument("--wide-to-hook", action="store_true",
                   help="put the 16:9 copy in the hook folder and move the square original into derived/")
    p.add_argument("--keep-poor", action="store_true", help="retry cut-outs that were skipped before")
    p.add_argument("--engine", choices=("auto", "pillow", "pure"), default="auto")
    p.add_argument("--limit", type=int, help="process at most N originals")
    p.add_argument("--dry-run", action="store_true", help="say what would be made, make nothing")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)
    variants = [v.strip() for v in a.variants.split(",") if v.strip()]
    bad = [v for v in variants if v not in ALL_VARIANTS]
    if bad:
        p.error("unknown variant(s): %s" % ", ".join(bad))
    bank = os.path.abspath(os.path.expanduser(a.bank))
    if not os.path.isdir(bank):
        log("ERROR bank folder not found: %s" % bank)
        return 2
    engine = pick_engine(a.engine)
    if engine.name != "pillow":
        log("using the built-in PNG code (Pillow not in use): slow, PNG only. "
            "For speed: sudo apt install python3-pil")
    opts = Options(variants, a.size, a.force, a.wide_to_hook, a.keep_poor, a.dry_run, a.quiet)
    t0 = time.time()
    c = run(bank, a.hook or bankfiles.HOOKS, engine, opts, a.limit, a.prune)
    log("%s %d file(s) from %d image(s), %d cut-out(s) skipped, %d failed, %.0f s" % (
        "would make" if a.dry_run else "made", c["made"], c["images"], c["skipped"], c["failed"],
        time.time() - t0))
    return 1 if c["failed"] and not c["made"] else 0


if __name__ == "__main__":
    sys.exit(main())
