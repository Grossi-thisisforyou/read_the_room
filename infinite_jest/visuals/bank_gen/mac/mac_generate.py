#!/usr/bin/env python3
"""Paint a large image library on a Mac (Apple Silicon), fast.

Uses the same descriptions (../prompts.py) and the same folders and .json
sidecars as the Pi's generate.py, so the results can be copied straight onto
the Pi. The painting is done by SD-Turbo through Hugging Face "diffusers" on
the Mac's graphics chip (PyTorch "mps").

You normally start this through generate_mac.sh (or by double-clicking
make_images.command), after running install_mac.sh once:

    ./generate_mac.sh --count 300                 # 300 images, spread over the hooks
    ./generate_mac.sh --per-hook 200              # top every hook up to 200 images
    ./generate_mac.sh --count 50 --hook flesh     # only one hook
    ./generate_mac.sh --count 300 --theme mix     # vary the theme image by image
    ./generate_mac.sh --count 300 --postprocess   # also make the 16:9 / grey / cut-out versions
    ./generate_mac.sh --check                     # is everything installed?
    ./generate_mac.sh --warmup                    # download the model, time one image

Ctrl+C once finishes the current image and stops; twice stops at once.
"""
import argparse
import os
import random
import signal
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BANK_GEN = os.path.dirname(HERE)
sys.path.insert(0, BANK_GEN)
import bankfiles  # noqa: E402
import generate  # noqa: E402  (stdlib only: shared helpers)
import pngio  # noqa: E402
import prompts  # noqa: E402

DEFAULT_BANK = os.path.expanduser("~/Desktop/infinite_jest_bank")
MODELS = {
    "sd-turbo": "stabilityai/sd-turbo",       # 512x512, small, fast (default)
    "sdxl-turbo": "stabilityai/sdxl-turbo",   # nicer detail, ~3x slower, bigger download
}
PI_TARGET = "pi@inartwetrust.local:read_the_room/infinite_jest/visuals/bank/"


def log(msg):
    print("%s  %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


# ------------------------------------------------------------------ painters

class DiffusersPainter:
    """SD-Turbo via diffusers on the Mac's GPU (mps), CPU as a slow fallback."""

    def __init__(self, model, device=None, precision="auto"):
        import torch
        from diffusers import AutoPipelineForText2Image
        self.torch = torch
        self.Auto = AutoPipelineForText2Image
        self.model = MODELS.get(model, model)
        if device is None:
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.device = device
        if device == "cpu":
            log("WARNING: the Mac's GPU (mps) is not available; painting on the CPU, much slower.")
        if precision == "auto":
            precision = "fp16" if device == "mps" else "fp32"
        self.precision = precision
        self._load()

    def _load(self):
        torch = self.torch
        dtype = torch.float16 if self.precision == "fp16" else torch.float32
        log("loading %s (%s on %s); the first time this downloads the model, a few GB" % (
            self.model, self.precision, self.device))
        try:
            pipe = self.Auto.from_pretrained(self.model, torch_dtype=dtype, variant="fp16")
        except (OSError, ValueError):  # model without fp16 files
            pipe = self.Auto.from_pretrained(self.model, torch_dtype=dtype)
        pipe = pipe.to(self.device)
        if self.device == "mps":
            # diffusers' advice for Apple Silicon with less than 64 GB of memory
            pipe.enable_attention_slicing()
        pipe.set_progress_bar_config(disable=True)
        self.pipe = pipe
        self.sampler = type(pipe.scheduler).__name__

    def paint(self, prompt, seed, steps, width, height, out_path):
        gen = self.torch.Generator("cpu").manual_seed(seed)
        img = self.pipe(prompt=prompt, num_inference_steps=steps, guidance_scale=0.0,
                        width=width, height=height, generator=gen).images[0]
        if img.convert("L").getextrema()[1] <= 2 and self.precision == "fp16":
            # all black: half precision overflowed (it happens on some setups).
            log("image came out black in half precision; switching to full precision (slower)")
            self.precision = "fp32"
            self._load()
            gen = self.torch.Generator("cpu").manual_seed(seed)
            img = self.pipe(prompt=prompt, num_inference_steps=steps, guidance_scale=0.0,
                            width=width, height=height, generator=gen).images[0]
        img.save(out_path, format="PNG")

    def info(self):
        return {"device": self.device, "precision": self.precision, "sampler": self.sampler,
                "model": self.model}


class FakePainter:
    """Stand-in for tests: no torch, writes a small flat PNG."""

    def __init__(self, *_a, **_k):
        self.delay = float(os.environ.get("FAKE_PAINT_SECONDS", "0"))

    def paint(self, prompt, seed, steps, width, height, out_path):
        time.sleep(self.delay)
        w, h = max(8, width // 16), max(8, height // 16)
        rgb = bytes(((seed >> 16) & 255, (seed >> 8) & 255, seed & 255))
        pngio.write(out_path, pngio.Raw(w, h, 3, rgb * (w * h)))

    def info(self):
        return {"device": "fake", "precision": "none", "sampler": "none", "model": "fake"}


# ------------------------------------------------------------------ checks

def check():
    ok = True
    print("python      %s (%s)" % (sys.version.split()[0], sys.executable))
    import platform
    print("machine     %s, macOS %s" % (platform.machine(), platform.mac_ver()[0] or "?"))
    if platform.machine() != "arm64":
        print("            not Apple Silicon: it will work on the CPU but slowly")
    for mod in ("torch", "diffusers", "transformers", "accelerate", "PIL"):
        try:
            m = __import__(mod)
            print("%-11s %s" % (mod, getattr(m, "__version__", "ok")))
        except Exception as e:  # noqa: BLE001
            print("%-11s MISSING (%s)" % (mod, e))
            ok = False
    try:
        import torch
        mps = torch.backends.mps.is_available()
        print("mps (GPU)   %s" % ("available" if mps else "NOT available (will use the CPU)"))
    except Exception:  # noqa: BLE001
        pass
    print("everything looks fine" if ok else "something is missing: run install_mac.sh again")
    return 0 if ok else 1


# ------------------------------------------------------------------ main loop

class Stopper:
    def __init__(self):
        self.stop = False
        signal.signal(signal.SIGINT, self.handle)

    def handle(self, *_):
        if self.stop:
            log("stopping now")
            sys.exit(130)
        self.stop = True
        log("will stop after this image (Ctrl+C again to stop at once)")


def next_hook(bank, rng, a):
    if a.hook:
        return a.hook
    counts = {h: len(generate.images_in(os.path.join(bank, h))) for h in prompts.HOOKS}
    if a.per_hook:
        short = [h for h in prompts.HOOKS if counts[h] < a.per_hook]
        if not short:
            return None
        return min(short, key=lambda h: (counts[h], rng.random()))
    return generate.pick_hook(bank, rng)


def make_one(painter, bank, hook, deck, rng, a):
    pr = prompts.make(hook, deck=deck, theme=a.theme)
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(0, 2**31 - 1)
    name = "%s_%d" % (time.strftime("%Y%m%d-%H%M%S"), seed)
    hook_dir = os.path.join(bank, hook)
    incoming = os.path.join(bank, ".incoming")
    os.makedirs(incoming, exist_ok=True)
    os.makedirs(hook_dir, exist_ok=True)
    tmp_png = os.path.join(incoming, name + ".png")
    t0 = time.time()
    painter.paint(pr["prompt"], seed, a.steps, a.width, a.height, tmp_png)
    seconds = time.time() - t0
    if not generate.looks_like_image(tmp_png):
        raise RuntimeError("the painter wrote no image")
    final = os.path.join(hook_dir, name + ".png")
    os.replace(tmp_png, final)
    info = painter.info()
    side = {"hook": hook}
    side.update(prompts.sidecar_fields(pr))
    side.update({
        "seed": seed,
        "model": info["model"],
        "steps": a.steps,
        "cfg_scale": 0.0,
        "sampler": info["sampler"],
        "width": a.width,
        "height": a.height,
        "device": info["device"],
        "precision": info["precision"],
        "seconds": round(seconds, 2),
        "created": bankfiles.now_iso(),
        "generator": "bank_gen/mac/mac_generate.py (diffusers)",
    })
    bankfiles.write_json_atomic(os.path.join(hook_dir, name + ".json"), side)
    return final, seconds, pr


def run(a, painter):
    bank = a.bank
    os.makedirs(bank, exist_ok=True)
    rng = random.Random()
    deck = prompts.PromptDeck(rng)
    known = generate.remember_bank(deck, bank)
    post_engine = None
    if a.postprocess:
        import postprocess
        post_engine = postprocess.pick_engine()
    stopper = Stopper()
    target = a.count if a.count is not None else (None if a.per_hook else 300)
    log("bank %s | %s steps %d, %dx%d | theme %s | %d images already known" % (
        bank, painter.info()["model"], a.steps, a.width, a.height, a.theme, known))
    made, failures, times = 0, 0, []
    t_start = time.time()
    while not stopper.stop and (target is None or made < target):
        hook = next_hook(bank, rng, a)
        if hook is None:
            log("every hook has at least %d images" % a.per_hook)
            break
        try:
            path, secs, pr = make_one(painter, bank, hook, deck, rng, a)
        except Exception as e:  # noqa: BLE001 - keep going on a bad image
            failures += 1
            log("FAILED (%s): %s" % (hook, e))
            if failures >= 3 and made == 0 or failures >= 10:
                log("too many failures, stopping")
                return 1
            continue
        failures = 0
        made += 1
        times.append(secs)
        rate = sum(times[-20:]) / len(times[-20:])
        left = (target - made) * rate if target else 0
        extra = ""
        if post_engine is not None:
            try:
                postprocess.process_one(path, hook, post_engine, postprocess.Options(quiet=True))
                extra = " +versions"
            except Exception as e:  # noqa: BLE001
                extra = " (postprocess failed: %s)" % e
        if a.max_per_hook:
            generate.enforce_cap(os.path.join(bank, hook), a.max_per_hook)
        log("[%s/%s] %-8s %.1f s%s%s  %s" % (
            made, target or "?", hook, secs, extra,
            ("  about %d min left" % round(left / 60) if left >= 90 else "  under 2 min left")
            if target and made > 1 and made < target else "",
            os.path.relpath(path, bank)))
    took = time.time() - t_start
    log("made %d image(s) in %.0f min (%.1f s each on average)" % (
        made, took / 60, (sum(times) / len(times)) if times else 0))
    print()
    print("To copy them onto the Pi (same Wi-Fi network), run:")
    print("    %s/copy_to_pi.sh \"%s\"" % (HERE, bank))
    print("or copy the folders inside %s onto a USB stick (see README)." % bank)
    return 0


def warmup(a, painter_cls):
    log("making one test image (this downloads the model the first time: be patient)")
    painter = painter_cls(a.model, a.device, a.precision)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "test.png")
        pr = prompts.make("flesh", rng=random.Random(1))
        painter.paint(pr["prompt"], 1, a.steps, a.width, a.height, out)   # first one is slow
        t0 = time.time()
        n = 3
        for i in range(n):
            painter.paint(pr["prompt"], 2 + i, a.steps, a.width, a.height, out)
        each = (time.time() - t0) / n
    log("works. Measured on this Mac: %.1f s per image at %d steps, so about %d images an hour." % (
        each, a.steps, 3600 / max(each, 0.01)))
    return 0


def parse_size(text):
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("--size wants WIDTHxHEIGHT, e.g. 512x512")
    if w % 8 or h % 8:
        raise argparse.ArgumentTypeError("width and height must be multiples of 8")
    return w, h


def main(argv=None):
    p = argparse.ArgumentParser(description="Paint the INFINITE JEST image bank on a Mac.")
    p.add_argument("--count", type=int, help="make this many images (default 300)")
    p.add_argument("--per-hook", type=int, help="instead: top every hook up to this many images")
    p.add_argument("--hook", choices=prompts.HOOKS, help="only this hook")
    p.add_argument("--bank", default=DEFAULT_BANK, help="output folder (default: %(default)s)")
    p.add_argument("--theme", default="mix",
                   help="mix (default: varied), auto (tonight's), none, or one of %s"
                   % ", ".join(prompts.THEME_NAMES))
    p.add_argument("--steps", type=int, default=2, help="1-4: more is slower and richer (default 2)")
    p.add_argument("--size", type=parse_size, default=(512, 512),
                   help="image size (default 512x512, what SD-Turbo is made for)")
    p.add_argument("--model", default="sd-turbo",
                   help="sd-turbo (default), sdxl-turbo, or a Hugging Face model id")
    p.add_argument("--device", choices=("mps", "cpu"), default=None, help="default: mps if available")
    p.add_argument("--precision", choices=("auto", "fp16", "fp32"), default="auto")
    p.add_argument("--seed", type=int, help="fixed seed (testing only)")
    p.add_argument("--postprocess", action="store_true",
                   help="also make the 16:9, grey, posterized and cut-out versions")
    p.add_argument("--max-per-hook", type=int, default=0, help="keep at most N per hook (default: no limit)")
    p.add_argument("--check", action="store_true", help="check the installation and stop")
    p.add_argument("--warmup", action="store_true", help="download the model, time a few images, stop")
    p.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)  # tests
    a = p.parse_args(argv)
    a.width, a.height = a.size
    a.bank = os.path.abspath(os.path.expanduser(a.bank))
    if not 1 <= a.steps <= 8:
        p.error("--steps should be between 1 and 4 (8 at most)")
    try:
        prompts.resolve_theme(a.theme)
    except ValueError as e:
        p.error(str(e))
    if a.check:
        return check()
    painter_cls = FakePainter if a.fake or os.environ.get("IJ_FAKE_PAINTER") == "1" else DiffusersPainter
    try:
        if a.warmup:
            return warmup(a, painter_cls)
        painter = painter_cls(a.model, a.device, a.precision)
    except ImportError as e:
        log("ERROR %s. Run install_mac.sh first (and start this with generate_mac.sh)." % e)
        return 2
    return run(a, painter)


if __name__ == "__main__":
    sys.exit(main())
