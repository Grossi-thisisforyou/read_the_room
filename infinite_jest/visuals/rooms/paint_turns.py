#!/usr/bin/env python3
"""One painter, two strands: the Pi's background painter takes turns.

Runs in place of ij-paint's ExecStart, inside the same service, so the rooms share
the painter's heat budget (its CPUQuota, Nice and pauses) instead of adding a second
generator. Each turn makes ONE picture:

    abstraction   bank_gen/generate.py --count 1 ...   (the colour fields and the dark face)
    room          rooms/make_rooms.py --count 1 --forget ...

A room is chosen --room-share of the time (default 0.35). Between turns it rests
--rest seconds and, above 70 C, waits until the Pi is below 60 C. While a visitor is
present (/tmp/infinite_jest_busy) both makers pause on their own.

    python3 paint_turns.py --model ~/sd-models/sd_turbo.safetensors \
        --taesd ~/sd-models/taesd.safetensors --rest 120 --room-share 0.35 --rooms-max 120 \
        -- <the usual generate.py options>
"""
import argparse
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_rooms  # noqa: E402

GEN = os.path.join(os.path.dirname(HERE), "bank_gen", "generate.py")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--taesd")
    p.add_argument("--sd-bin", default="/usr/local/bin/ij-sd")
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--room-share", type=float, default=0.35)
    p.add_argument("--rooms-max", type=int, default=120)
    p.add_argument("--rest", type=float, default=120)
    p.add_argument("gen_args", nargs=argparse.REMAINDER, help="after --: options for generate.py")
    a = p.parse_args()
    gen_args = [x for x in a.gen_args if x != "--"]
    rng = random.Random()
    while True:
        make_rooms.wait_until_calm()
        if rng.random() < a.room_share:
            cmd = [sys.executable, os.path.join(HERE, "make_rooms.py"), "--painter", "sdcpp",
                   "--sd-bin", a.sd_bin, "--model", a.model, "--threads", str(a.threads),
                   "--steps", "1", "--size", "384", "--count", "1", "--forget", "--max", str(a.rooms_max)]
            if a.taesd:
                cmd += ["--taesd", a.taesd]
        else:
            cmd = [sys.executable, GEN, "--count", "1", "--anytime", "--sd-bin", a.sd_bin,
                   "--model", a.model, "--threads", str(a.threads)] + gen_args
            if a.taesd and "--taesd" not in " ".join(gen_args):
                cmd += ["--", "--taesd", a.taesd]
        subprocess.run(cmd)
        time.sleep(a.rest)


if __name__ == "__main__":
    main()
