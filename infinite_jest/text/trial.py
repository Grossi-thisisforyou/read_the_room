"""Try the oracle prompts against the real model on the Pi and score them.

    python3 -m infinite_jest.text.trial --url http://127.0.0.1:8080 --n 20
    python3 -m infinite_jest.text.trial --dry      # no model: print one prompt

For each of N simulated profiles it asks for words and a dossier, runs the
answers through the style check, and prints the pass rate, the time per call,
and every answer with the rule it broke. Run it with Qwen2.5-1.5B and 3B at
the mini showing and keep whichever passes more often within ~8 s.
Nothing about real visitors is involved: profiles are random.
"""

import argparse
import json
import random
import time
import urllib.request

from . import oracle_prompt, style

FEATS = {
    "handled": lambda r: round(r.uniform(0.2, 1.0), 2),
    "tilt_range": lambda r: r.randint(20, 180),
    "tilt_speed": lambda r: r.randint(10, 160),
    "closeness": lambda r: round(r.uniform(0.1, 0.9), 2),
    "approach_time": lambda r: r.randint(1, 15),
    "voice": lambda r: round(r.uniform(0, 0.6), 2),
    "touch_rate": lambda r: round(r.uniform(0, 30), 1),
    "choice_speed": lambda r: round(r.uniform(0.6, 6), 1),
    "shake": lambda r: round(r.uniform(0.01, 0.5), 2),
    "dwell": lambda r: r.randint(20, 170),
}
HOOKS = ["flesh", "scrawl", "inverted", "mirror", "void"]
STYLES = ["social", "solitary", "novel", "plain", "orderly", "loose", "warm", "blunt", "reassuring", "cold"]


def fake_profile(r):
    feats = {k: f(r) for k, f in FEATS.items()}
    evidence = ["{} -> {}{}".format(k, r.choice("OCEAN"), r.choice("+-"))
                for k in r.sample(sorted(feats), 4)]
    return {"ocean": {t: round(r.uniform(0.15, 0.9), 2) for t in "OCEAN"},
            "trait_confidence": {t: round(r.uniform(0.1, 0.8), 2) for t in "OCEAN"},
            "confidence": round(r.uniform(0.4, 0.95), 2), "hook": r.choice(HOOKS),
            "segment": r.choice(["The Performer", "The Lurker", "The Seeker", "The Auditor"]),
            "hook_params": {"prompt_style": r.choice(STYLES)},
            "features": feats, "evidence": evidence}


def call(url, body, timeout):
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = json.loads(resp.read())["choices"][0]["message"]["content"]
    return text, time.time() - t0


def why(text, kind):
    lines = style._split_lines(text)
    regs = (["whisper"] + ["log"] * 3) if kind == "words" else ["confession"] * 5
    out = []
    for l, reg in zip(lines, regs):
        l2 = l.lower() if reg != "log" else l.upper()
        p = style.check(l2, reg, 4 if reg == "log" else (14 if reg == "confession" else None))
        if p:
            out.append("{!r}: {}".format(l, p))
    return "; ".join(out) or ("too few lines" if len(lines) < 2 else "?")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--dry", action="store_true", help="print one request and exit")
    a = ap.parse_args(argv)
    r = random.Random(a.seed)
    if a.dry:
        p = fake_profile(r)
        print(json.dumps(oracle_prompt.request_body(oracle_prompt.words_messages(p), "words"), indent=1))
        return 0
    stats = {"words": [0, 0, []], "dossier": [0, 0, []]}
    for i in range(a.n):
        p = fake_profile(r)
        for kind, build, clean in (("words", oracle_prompt.words_messages, style.clean_words),
                                   ("dossier", oracle_prompt.dossier_messages, style.clean_dossier)):
            try:
                text, dt = call(a.url, oracle_prompt.request_body(build(p), kind), a.timeout)
            except Exception as e:  # noqa: BLE001 - report and go on
                print("[{} {}] model error: {}".format(i, kind, e))
                continue
            s = stats[kind]
            s[1] += 1
            s[2].append(dt)
            good = clean(text)
            s[0] += bool(good)
            print("[{} {} {:.1f}s {}]\n{}".format(i, kind, dt, "PASS" if good else "DROP", text.strip()))
            if not good:
                print("  -> " + why(text, kind))
    for kind, (ok, n, times) in stats.items():
        if n:
            times.sort()
            print("{}: {}/{} pass ({:.0%}), median {:.1f}s, slowest {:.1f}s".format(
                kind, ok, n, ok / n, times[len(times) // 2], times[-1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
