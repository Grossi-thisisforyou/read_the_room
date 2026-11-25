#!/usr/bin/env python3
"""Dream up haunted rooms and put them in the image bank, ready for the show.

Writes, for every room:

    <bank>/room/<stamp>_<seed>.png            the graded picture the show uses (1280x720)
    <bank>/room/<stamp>_<seed>.json           prompt, tags (kind: room ...), seed, model
    <bank>/room/derived/<stamp>_<seed>.raw.png  what the model made, ungraded
                                              (the show skips "derived" folders)

Two painters, the same prompts:

  On the Mac (ahead of time, as a pack; nicer, 512 px, 4 steps):
      python3 make_rooms.py --painter diffusers --count 24 --bank ~/Desktop/infinite_jest_rooms
    Uses SD-Turbo through diffusers, from the Hugging Face cache, or a local file:
      --model ~/path/sd_turbo.safetensors

  On the Pi (slowly, in the background, like ij-paint; pauses while a visitor is here):
      python3 make_rooms.py --painter sdcpp --sd-bin /usr/local/bin/ij-sd \
          --model ~/sd-models/sd_turbo.safetensors --steps 1 --size 384 --threads 2 --forever
    Only run this when the Pi is cool. It waits while /tmp/infinite_jest_busy exists.

Also --dry-run (print prompts only) and --painter fake (tests).
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rooms  # noqa: E402

PAUSE_FILE = "/tmp/infinite_jest_busy"


def log(msg):
    print("%s  %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


class Diffusers:
    def __init__(self, model, device=None):
        import torch
        self.torch = torch
        device = device or ("mps" if torch.backends.mps.is_available()
                            else "cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.float16 if device in ("mps", "cuda") else torch.float32
        model = os.path.expanduser(model)
        if os.path.isfile(model):
            from diffusers import StableDiffusionPipeline
            pipe = StableDiffusionPipeline.from_single_file(model, torch_dtype=dtype)
        else:
            from diffusers import AutoPipelineForText2Image
            try:
                pipe = AutoPipelineForText2Image.from_pretrained(model, torch_dtype=dtype, variant="fp16")
            except (OSError, ValueError):
                pipe = AutoPipelineForText2Image.from_pretrained(model, torch_dtype=dtype)
        pipe = pipe.to(device)
        if device == "mps":
            pipe.enable_attention_slicing()
        pipe.set_progress_bar_config(disable=True)
        self.pipe, self.device, self.name = pipe, device, os.path.basename(model)

    def paint(self, prompt, negative, seed, steps, size, out):
        g = self.torch.Generator("cpu").manual_seed(seed)
        img = self.pipe(prompt=prompt, num_inference_steps=steps, guidance_scale=0.0,
                        width=size, height=size, generator=g).images[0]
        img.save(out)


class SdCpp:
    """stable-diffusion.cpp (the Pi's ij-sd), one process per picture, niced, paused
    while a visitor is in the room."""

    def __init__(self, sd_bin, model, threads, taesd=None):
        self.sd_bin, self.model, self.threads, self.taesd = sd_bin, os.path.expanduser(model), threads, taesd
        self.name = os.path.basename(self.model)

    def paint(self, prompt, negative, seed, steps, size, out):
        wait_until_calm()
        cmd = (["nice", "-n", "15"] if shutil.which("nice") else []) + \
              (["ionice", "-c3"] if shutil.which("ionice") else []) + [
            self.sd_bin, "-m", self.model, "-p", prompt, "-n", negative,
            "--steps", str(steps), "--cfg-scale", "1", "-W", str(size), "-H", str(size),
            "--seed", str(seed), "-t", str(self.threads), "-o", out]
        if self.taesd:
            cmd += ["--taesd", os.path.expanduser(self.taesd)]
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        paused = False
        while p.poll() is None:
            busy = os.path.exists(PAUSE_FILE)
            if busy != paused:
                p.send_signal(19 if busy else 18)      # SIGSTOP / SIGCONT
                paused = busy
            time.sleep(1)
        if p.returncode != 0 or not os.path.exists(out):
            raise RuntimeError("ij-sd failed (%s)" % p.returncode)


HOT_C, COOL_C = 70.0, 60.0      # stop above HOT, start again below COOL


def cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def other_painter_running():
    """True while another picture is being made (ij-paint's ij-sd): one at a time, for the heat."""
    try:
        out = subprocess.run(["pgrep", "-x", "ij-sd"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return bool(out.strip())


def wait_until_calm():
    said = ""
    while True:
        t = cpu_temp()
        if os.path.exists(PAUSE_FILE):
            why = "a visitor is here"
        elif t is not None and t > HOT_C or (said.startswith("hot") and t is not None and t > COOL_C):
            why = "hot (%.0f C), cooling down" % t
        elif other_painter_running():
            why = "the other painter is working"
        else:
            if said:
                log("ready")
            return
        if why != said:
            log("waiting: " + why)
            said = why
        time.sleep(20)


class Fake:
    name = "fake"

    def paint(self, prompt, negative, seed, steps, size, out):
        import numpy as np
        from PIL import Image
        r = np.random.default_rng(seed)
        a = np.linspace(0, 255, size)[None, :, None] * r.uniform(0.2, 1, (1, 1, 3))
        Image.fromarray(np.broadcast_to(a, (size, size, 3)).astype("uint8")).save(out)


def make_one(painter, a, deck, rng):
    import grade
    from PIL import Image
    pr = rooms.make(deck=deck, palette=a.palette)
    seed = rng.randrange(2 ** 31 - 1)
    name = "%s_%d" % (time.strftime("%Y%m%d-%H%M%S"), seed)
    if a.dry_run:
        print("%s\n  %s\n" % (" ".join(pr["tag_list"][1:]), pr["prompt"]))
        return
    room_dir = os.path.join(a.bank, "room")
    derived = os.path.join(room_dir, "derived")
    incoming = os.path.join(a.bank, ".incoming")
    for d in (derived, incoming):
        os.makedirs(d, exist_ok=True)
    raw = os.path.join(derived, name + ".raw.png")
    t0 = time.time()
    painter.paint(pr["prompt"], pr["negative"], seed, a.steps, a.size, raw)
    tmp = os.path.join(incoming, name + ".png")
    grade.grade(Image.open(raw), pr["tags"]["palette"], a.strength, seed).save(tmp)
    side = {"kind": "room", "hook": "room", "prompt": pr["prompt"], "negative": pr["negative"],
            "tags": pr["tags"], "tag_list": pr["tag_list"], "signature": pr["signature"],
            "prompt_version": pr["prompt_version"], "seed": seed, "model": painter.name,
            "steps": a.steps, "size": a.size, "grade_strength": a.strength,
            "seconds": round(time.time() - t0, 1), "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "generator": "visuals/rooms/make_rooms.py"}
    with open(os.path.join(room_dir, name + ".json"), "w") as f:
        json.dump(side, f, indent=2)
    os.replace(tmp, os.path.join(room_dir, name + ".png"))      # last: the show sees it complete
    log("room %s  %-28s %.0f s" % (name, " ".join("%s" % pr["tags"][k] for k in ("room", "haunt", "palette")),
                                   time.time() - t0))


def main(argv=None):
    p = argparse.ArgumentParser(description="Dream up haunted rooms for the INFINITE JEST bank.")
    p.add_argument("--painter", choices=("diffusers", "sdcpp", "fake"), default="diffusers")
    p.add_argument("--model", default="stabilityai/sd-turbo")
    p.add_argument("--sd-bin", default="/usr/local/bin/ij-sd")
    p.add_argument("--taesd")
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--bank", default=os.path.normpath(os.path.join(HERE, "..", "bank")))
    p.add_argument("--count", type=int, default=12)
    p.add_argument("--forever", action="store_true", help="keep going (Pi background use)")
    p.add_argument("--rest", type=float, default=0, help="seconds to rest between rooms (keeps the Pi cool)")
    p.add_argument("--max", type=int, default=120, help="keep at most this many rooms (oldest go)")
    p.add_argument("--forget", action="store_true",
                   help="past --max, old rooms fade out slowly instead of vanishing at once")
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--strength", type=float, default=0.65, help="how far the palette grade pulls (0-1)")
    p.add_argument("--palette", choices=sorted(rooms.PALETTES), help="force one palette")
    p.add_argument("--seed", type=int)
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    a.bank = os.path.abspath(os.path.expanduser(a.bank))
    rng = random.Random(a.seed)
    deck = rooms.Deck(random.Random(a.seed))
    painter = None
    if not a.dry_run:
        painter = {"diffusers": lambda: Diffusers(a.model),
                   "sdcpp": lambda: SdCpp(a.sd_bin, a.model, a.threads, a.taesd),
                   "fake": Fake}[a.painter]()
        log("painter %s | %d steps, %d px | bank %s" % (painter.name, a.steps, a.size, a.bank))
    n = 0
    while a.forever or n < a.count:
        try:
            make_one(painter, a, deck, rng)
        except KeyboardInterrupt:
            break
        except Exception as e:  # noqa: BLE001  one bad picture never stops the night
            log("!! %s" % e)
            time.sleep(30)
        n += 1
        if not a.dry_run:
            if a.forget:
                forget(os.path.join(a.bank, "room"), a.max, rng)
            _cap(os.path.join(a.bank, "room"), a.max + 40)        # hard ceiling for the card
            if a.rest:
                time.sleep(a.rest)
    return 0


def forget(room_dir, keep, rng, steps=4):
    """The library forgets. Past `keep` rooms, a few old ones start to fade: each night-cycle
    one of them gets darker, softer and smaller, and after `steps` fades it is gone.
    Which one fades is chosen at random, older ones more likely, so now and then an
    old room survives a long time. The show simply sees the faded file."""
    from PIL import Image, ImageEnhance, ImageFilter
    pngs = sorted((f for f in os.listdir(room_dir) if f.endswith(".png")),
                  key=lambda f: os.path.getmtime(os.path.join(room_dir, f)))
    extra = len(pngs) - keep
    if extra <= 0 or not pngs:
        return
    weights = [(len(pngs) - i) ** 2 for i in range(len(pngs))]      # oldest weigh most
    for _ in range(min(extra, 3)):
        f = rng.choices(pngs, weights=weights)[0]
        stem, path = f[:-4], os.path.join(room_dir, f)
        side_path = os.path.join(room_dir, stem + ".json")
        try:
            with open(side_path) as fh:
                side = json.load(fh)
        except (OSError, ValueError):
            side = {}
        n = int(side.get("faded", 0)) + 1
        if n >= steps:
            for p in (path, side_path, os.path.join(room_dir, "derived", stem + ".raw.png")):
                try:
                    os.remove(p)
                except OSError:
                    pass
            log("forgot %s" % stem)
        else:
            st = os.stat(path)
            img = Image.open(path).convert("RGB")
            w, h = img.size
            img = img.resize((max(16, w * 2 // 3), max(9, h * 2 // 3))).resize((w, h))
            img = img.filter(ImageFilter.GaussianBlur(1.5 * n))
            img = ImageEnhance.Brightness(img).enhance(0.8)
            img = ImageEnhance.Color(img).enhance(0.7)
            tmp = path + ".tmp.png"
            img.save(tmp)
            os.replace(tmp, path)
            os.utime(path, (st.st_atime, st.st_mtime))       # keeps its age: fading is not new
            side["faded"] = n
            with open(side_path, "w") as fh:
                json.dump(side, fh, indent=2)
            log("fading %s (%d/%d)" % (stem, n, steps))
        pngs.remove(f)                     # at most one fade per room per cycle
        weights = [(len(pngs) - i) ** 2 for i in range(len(pngs))]
        if not pngs:
            break


def _cap(room_dir, keep):
    pngs = sorted((f for f in os.listdir(room_dir) if f.endswith(".png")),
                  key=lambda f: os.path.getmtime(os.path.join(room_dir, f)))
    for f in pngs[:max(0, len(pngs) - keep)]:
        stem = f[:-4]
        for path in (f, stem + ".json", os.path.join("derived", stem + ".raw.png")):
            try:
                os.remove(os.path.join(room_dir, path))
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
