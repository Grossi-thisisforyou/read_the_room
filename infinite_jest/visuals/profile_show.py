"""Frame times in a realistic show, phase by phase and scene by scene.

    python3 -m infinite_jest.visuals.profile_show              # ~5 min show, about 2-3 min to run
    python3 -m infinite_jest.visuals.profile_show --quick      # shorter visits
    python3 -m infinite_jest.visuals.profile_show --cprofile   # + the 25 hottest functions
    python3 -m infinite_jest.visuals.profile_show --tracemalloc  # + allocation churn per frame
    python3 -m infinite_jest.visuals.profile_show --slow 2.0   # pretend the machine is 2x slower
                                                              # (exercises the quality governor)
    python3 -m infinite_jest.visuals.profile_show --level 3    # pin a governor quality level

bench.py times one hook at a time in a steady state. A show is not steady:
grounds are painted while scenes change, a 200-image library feeds the
underpaintings and collage figures, the camera sends frames at 4 fps, the
profiler changes its mind about the hook, the hinge drops the room, the
visitor's file types itself out at 1080p, the wipe paints the room over, and
one visitor covers the eye (opted out). This walks through all of it at the
show's 30 fps time step (on one core: run it with `taskset -c 0` for honest
Pi-like numbers) and prints p50 / p95 / p99 / max per phase and per scene.

Each visit follows the show's timings (approach 3 s, profiling 16 s, hook,
hinge 4 s before the hook ends, release with the file typed out line by
line, wipe 12 s); --quick shortens hook and release.
"""
import argparse
import math
import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402
import pygame  # noqa: E402

HOOKS = ("flesh", "scrawl", "inverted", "mirror", "void")
REVEAL = ["PICKED UP AT 17:42:10", "TILTED LEFT 41 TIMES", "HELD STILL 9 S", "LOOKED AWAY 3X",
          "RETURNED TO THE FACE", "CHOSE: STAY", "SEGMENT: LINGERER", "CONFIDENCE 0.81",
          "STOOD LEFT OF CENTRE, CLOSER EVERY TIME THE BASS CAME BACK"]


def fake_bank(root, n_per_hook=40, seed=0):
    """A 200-image library like bank_gen's: bank/<hook>/derived/<name>.poster.png
    (512x288, painterly noise) and every other one a .cutout.png (RGBA figure)."""
    rng = np.random.default_rng(seed)
    for hi, hook in enumerate(HOOKS):
        d = os.path.join(root, hook, "derived")
        os.makedirs(d, exist_ok=True)
        for i in range(n_per_hook):
            base = os.path.join(d, "2026111%d-%04d_1" % (i % 9, i))
            arr = rng.integers(0, 255, (64, 36, 3)).astype(np.uint8)
            s = pygame.transform.smoothscale(pygame.surfarray.make_surface(arr), (512, 288))
            pygame.image.save(s, base + ".poster.png")
            if i % 2 == 0:
                c = pygame.Surface((200, 400), pygame.SRCALPHA)
                col = tuple(int(v) for v in rng.integers(60, 230, 3)) + (255,)
                pygame.draw.ellipse(c, col, (60, 10, 80, 100))
                pygame.draw.ellipse(c, col, (20, 100, 160, 300))
                pygame.image.save(c, base + ".cutout.png")
    return root


def visit_timeline(vid, hooks, ocean, quick=False, opt_out_at=None):
    """[(phase, duration, extra)] for one visitor. hooks: [(hook, from hook_t)]."""
    hook_s = 60.0 if quick else 110.0
    rel_s = 24.0 if quick else 50.0
    return dict(vid=vid, ocean=ocean, hooks=hooks, opt_out_at=opt_out_at,
                segs=[("approach", 3.0), ("profiling", 16.0 if not quick else 10.0), ("hook", hook_s),
                      ("release", rel_s), ("wipe", 12.0)])


def show(quick=False):
    """The show: idle, three visitors (the third covers the eye during its hook)."""
    oc = [dict(O=0.4, C=0.5, E=0.35, A=0.2, N=0.85), dict(O=0.85, C=0.2, E=0.6, A=0.5, N=0.5),
          dict(O=0.6, C=0.7, E=0.75, A=0.6, N=0.3)]
    items = [("idle", 8.0),
             visit_timeline("v-a17c", [("flesh", 0), ("scrawl", 40)], oc[0], quick),
             ("idle", 6.0),
             visit_timeline("v-3e90", [("inverted", 0), ("mirror", 25), ("void", 50)], oc[1], quick),
             ("idle", 4.0),
             visit_timeline("v-c4d2", [("mirror", 0), ("flesh", 30)], oc[2], quick, opt_out_at=20.0)]
    return items


def states(items, dt):
    """Yields (t, state) for the whole show at the time step dt."""
    t = 0.0
    for it in items:
        if isinstance(it, tuple):
            n = int(it[1] / dt)
            for i in range(n):
                yield t, {"visitor_id": "", "phase": "idle", "phase_t": i * dt, "intensity": 0.12,
                          "hook": "", "steer": {"x": 0.0, "y": 0.0, "flip": False, "shake": 0.0}}
                t += dt
            continue
        opted = False
        for ph, dur in it["segs"]:
            n = int(dur / dt)
            for i in range(n):
                pt = i * dt
                k = pt / dur
                hook = it["hooks"][0][0]
                if ph in ("hook", "release"):
                    for h, at in it["hooks"]:
                        if ph == "release" or pt >= at:
                            hook = h
                conv = 0.0 if ph == "approach" else (min(1.0, pt / (dur * 0.8)) if ph == "profiling" else 1.0)
                oc = {key: 0.5 + (v - 0.5) * conv for key, v in it["ocean"].items()}
                inten = {"approach": 0.3, "profiling": 0.55, "hook": 0.75 + 0.2 * k, "release": 0.4,
                         "wipe": 0.15}[ph]
                x = math.sin(t * 2 * math.pi / 11.0) * (0.4 + 0.5 * math.sin(t / 7.0) ** 2)
                y = math.sin(t * 2 * math.pi / 17.0 + 1.0) * 0.8
                shake = 0.8 if (t % 23.0) < 0.3 and ph in ("profiling", "hook") else 0.0
                st = {"visitor_id": it["vid"] if ph != "wipe" else "", "phase": ph, "phase_t": pt,
                      "intensity": inten, "ocean": oc, "hook": hook if ph != "approach" else "",
                      "words": ["LINGERED %dS" % int(pt + 4), "LEFT HAND", "LOOKED AWAY 3X"],
                      "steer": {"x": x, "y": y, "flip": False, "shake": shake}}
                if ph == "hook" and it["opt_out_at"] is not None and pt >= it["opt_out_at"]:
                    opted = True
                if opted and ph in ("hook", "release"):
                    st["opted_out"] = True
                if ph == "hook" and pt >= dur - 4.0:
                    st["hinge"] = True
                    st["big_line"] = "NOW IT GOES"
                elif ph == "hook" and 15 < pt < 21:
                    st["big_line"] = "YOU STAYED FOR THIS"
                if ph in ("release", "wipe") and not opted:
                    nl = len(REVEAL) if ph == "wipe" else min(len(REVEAL), 1 + int(pt / 3.0))
                    rv = {"header": "FILE %s" % it["vid"][-4:].upper(), "label": "WHAT THE ROOM KEPT",
                          "lines": REVEAL[:nl], "total": len(REVEAL)}
                    if ph == "wipe":
                        rv["struck"] = min(len(REVEAL), int(pt * 1.3))
                        rv["wipe"] = ["DELETED", "NOTHING KEPT"][: 1 + int(pt > 5)]
                    st["reveal"] = rv
                yield t, st
                t += dt


def camera_frames(n=40):
    """A 10 s loop of N900-like gray frames (160x120) at 4 fps; made once,
    outside the timing."""
    from .figure import ghost_body
    body = [ghost_body(160, 120, i * 0.25, seed=5, present=1.0, close=(i // 20) % 2 == 1, cam_shake=0.6)
            for i in range(n)]
    empty = [ghost_body(160, 120, i * 0.25, seed=5, present=0.0) for i in range(8)]
    return body, empty


def pct(xs, q):
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


def table(title, groups):
    print("\n%s" % title)
    print("  %-26s %6s %7s %7s %7s %7s" % ("", "frames", "p50", "p95", "p99", "max"))
    for name, xs in groups:
        if xs:
            print("  %-26s %6d %7.1f %7.1f %7.1f %7.1f" % (name[:26], len(xs), pct(xs, 0.5), pct(xs, 0.95),
                                                        pct(xs, 0.99), max(xs)))


def run(args):
    from . import create
    pygame.display.init()
    pygame.font.init()
    tmp = tempfile.mkdtemp(prefix="ij_bank_")
    try:
        bank = fake_bank(tmp) if not args.no_bank else None
        out = pygame.Surface(tuple(args.size))
        cfg = {"busy_file": None, "bank_dir": bank, "bank_reload_s": 120}
        if args.internal:
            cfg["internal_size"] = tuple(args.internal)
        if args.no_smooth:
            cfg["smooth_scale"] = False
        if args.budget:
            cfg["frame_budget_ms"] = args.budget
        if args.no_governor:
            cfg["frame_budget_ms"] = 0
        vis = create(tuple(args.size), cfg)
        if args.level is not None:
            # pin one quality level (see governor.py) to measure what it costs
            vis.governor.enabled = False
            vis._apply_quality(args.level)
        slow = max(1.0, args.slow)
        if slow > 1.0:
            # an artificially slow machine: every frame's work takes `slow` times
            # as long (the extra is slept inside render, so the governor sees it)
            real = vis._render

            def slowed(surface, dt, real=real):
                a = time.perf_counter()
                real(surface, dt)
                time.sleep((time.perf_counter() - a) * (slow - 1.0))
            vis._render = slowed
        body, empty = camera_frames()
        dt = 1 / 30
        items = show(args.quick)
        per_phase, per_scene, loop_all = {}, {}, []
        cam_i = 0
        prof = None
        if args.cprofile:
            import cProfile
            prof = cProfile.Profile()
        if args.tracemalloc:
            import tracemalloc
            tracemalloc.start(8)
            snap0 = None
        nframes = 0
        wall0 = time.perf_counter()
        for t, st in states(items, dt):
            frame = None
            if int((t + dt) * 4) != int(t * 4):
                if st["phase"] == "idle":
                    frame = empty[cam_i % len(empty)]
                else:
                    frame = body[cam_i % len(body)]
                cam_i += 1
            if prof:
                prof.enable()
            a = time.perf_counter()
            vis.on_state(st)
            if frame is not None:
                vis.on_frame(frame)
            vis.render(out, dt)
            ms = (time.perf_counter() - a) * 1000
            if prof:
                prof.disable()
            nframes += 1
            if args.tracemalloc and nframes == 300:
                snap0 = tracemalloc.take_snapshot()
            if nframes < 30:
                continue     # start-up
            name = st["phase"] + ("/opted_out" if st.get("opted_out") else "") + \
                ("/hinge" if st.get("hinge") else "")
            per_phase.setdefault(name, []).append(ms)
            sname = (vis.scene or {}).get("name", "?")
            per_scene.setdefault(sname, []).append(ms)
            loop_all.append(ms)
        wall = time.perf_counter() - wall0
        print("Show: %d frames (%.0f s at 30 fps) in %.0f s; output %dx%d, internal %dx%d, smooth %s, bank %s"
              % (nframes, nframes / 30, wall, args.size[0], args.size[1], vis.W, vis.H,
                 "on" if vis.smooth else "off", "200 images" if bank else "none"))
        print("Times are on_state + on_frame + render per frame, in ms.")
        table("All frames", [("all", loop_all)])
        order = ["idle", "approach", "profiling", "hook", "hook/hinge", "hook/opted_out", "hook/opted_out/hinge",
                 "release", "release/opted_out", "wipe"]
        table("Per phase", [(k, per_phase[k]) for k in order if k in per_phase] +
              [(k, v) for k, v in per_phase.items() if k not in order])
        table("Per scene", sorted(per_scene.items(), key=lambda kv: -pct(kv[1], 0.5)))
        gov = getattr(vis, "governor", None)
        if gov is not None and gov.log:
            print("\nQuality governor (budget %.0f ms):" % gov.budget)
            for line in gov.log:
                print("  " + line)
        if prof:
            import io
            import pstats
            s = io.StringIO()
            pstats.Stats(prof, stream=s).sort_stats("tottime").print_stats(25)
            print("\ncProfile, by own time:")
            print("\n".join(s.getvalue().splitlines()[:45]))
        if args.tracemalloc and snap0 is not None:
            import tracemalloc
            snap1 = tracemalloc.take_snapshot()
            print("\ntracemalloc: blocks alive since frame 300 (growth), top 12:")
            for stat in snap1.compare_to(snap0, "lineno")[:12]:
                print("  ", stat)
            cur, peak = tracemalloc.get_traced_memory()
            print("  traced now %.1f MB, peak %.1f MB" % (cur / 1e6, peak / 1e6))
        return dict(all=loop_all, phase=per_phase, scene=per_scene)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="shorter hook and release")
    ap.add_argument("--size", type=int, nargs=2, default=(1920, 1080))
    ap.add_argument("--internal", type=int, nargs=2)
    ap.add_argument("--no-smooth", action="store_true")
    ap.add_argument("--no-bank", action="store_true")
    ap.add_argument("--budget", type=float, help="frame_budget_ms for the quality governor")
    ap.add_argument("--no-governor", action="store_true")
    ap.add_argument("--level", type=int, choices=(0, 1, 2, 3), help="pin the governor at this quality level")
    ap.add_argument("--slow", type=float, default=1.0, help="pretend frames take this many times longer")
    ap.add_argument("--cprofile", action="store_true")
    ap.add_argument("--tracemalloc", action="store_true")
    args = ap.parse_args(argv)
    run(args)


if __name__ == "__main__":
    sys.exit(main())
