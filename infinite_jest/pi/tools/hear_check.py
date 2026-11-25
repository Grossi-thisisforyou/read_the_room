#!/usr/bin/env python3
"""Check speech to text on this machine: say a sentence with the room's own voice, understand it.

    python3 tools/hear_check.py            prints what it understood, how long it took, and "ok"
    python3 tools/hear_check.py --mic      instead: understand the last 5 seconds from the microphone (ij-room)
"""
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
from showengine import hear  # noqa: E402


def main():
    h = hear.Hearing({})
    path = hear.find_model()
    print("model:", path or "none in ~/models/whisper")
    if path is None:
        return 1
    if "--mic" in sys.argv:
        audio = hear.fetch(5.0)
        if audio is None:
            print("the microphone program (ij-room) did not answer on 127.0.0.1:8769")
            return 1
        want = None
    else:
        from infinite_jest.audio import speech
        got = speech._neural("i grew up in a small house by the sea") or speech._espeak("i grew up in a small house by the sea", speed=140, pitch=40)
        if got is None:
            print("no voice to test with")
            return 1
        x, sr = got
        audio = np.interp(np.arange(0, len(x), sr / 16000.0), np.arange(len(x)), x).astype(np.float32)
        want = ("house", "sea")
    out = []
    h._fetch = lambda s: audio
    t0 = time.time()
    h.listen(5.0, out.append)
    while not out and time.time() - t0 < 120:
        time.sleep(0.1)
    text = out[0] if out else ""
    print("understood: %r in %.1f s (model load included)" % (text, time.time() - t0))
    ok = bool(text) and (want is None or any(w in text.lower() for w in want))
    print("ok" if ok else "not ok")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
