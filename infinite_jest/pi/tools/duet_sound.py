#!/usr/bin/env python3
"""The sound for a duet_preview video: the real music engine fed with the preview's states,
and the room's spoken lines (espeak-ng) on top.

    python3 tools/duet_sound.py states.jsonl out.wav        (run from infinite_jest/pi)
"""
import json
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from infinite_jest.audio.ambient import AmbientSynth  # noqa: E402
from infinite_jest.audio.speech import Speech, _espeak, treat  # noqa: E402


def main():
    src, out = sys.argv[1:3]
    rows = [json.loads(line) for line in open(src)]
    said_p = os.path.splitext(src)[0] + "-said.json"
    said = json.load(open(said_p)) if os.path.exists(said_p) else []
    synth = AmbientSynth(seed=int(sys.argv[3]) if len(sys.argv) > 3 else 0, volume=0.9)
    speech = Speech()
    w = wave.open(out, "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(48000)
    t, i, was_wipe = 0.0, 0, False
    while t < rows[-1]["t"]:
        while i < len(rows) - 1 and rows[i + 1]["t"] <= t:
            i += 1
        st = {k: v for k, v in rows[i].items() if k != "t"}
        synth.set_state(st)
        if st.get("phase") == "wipe" and not was_wipe:
            synth.wipe()
        was_wipe = st.get("phase") == "wipe"
        while said and said[0][0] <= t:
            sig = treat(*(_espeak(said.pop(0)[1]) or (None, 1)))
            if sig is not None:
                speech._queue.append(sig)
        w.writeframes(np.ascontiguousarray(speech.mix(synth.render_block())).tobytes())
        t += synth.B / 48000.0
    w.close()


if __name__ == "__main__":
    main()
