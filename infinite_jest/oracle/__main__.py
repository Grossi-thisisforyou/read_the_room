"""Run the oracle.

    python3 -m infinite_jest.oracle --ws ws://127.0.0.1:8765/ws        # in the show
    python3 -m infinite_jest.oracle --try performer                    # one test call to the local model
    python3 -m infinite_jest.oracle --try performer --url http://127.0.0.1:8080/v1/chat/completions
"""

import argparse
import sys
import time

from .oracle import DEFAULTS, Oracle, http_complete, run_forever


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m infinite_jest.oracle")
    ap.add_argument("--ws", help="engine WebSocket url")
    ap.add_argument("--url", default=DEFAULTS["url"], help="llama-server chat completions url")
    ap.add_argument("--model", default=DEFAULTS["model"])
    ap.add_argument("--try", dest="try_", metavar="ARCHETYPE",
                    help="simulate a visitor and ask the model once for words and dossier")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args(argv)
    cfg = {"url": a.url, "model": a.model}
    if a.try_:
        from infinite_jest.profiler import sim
        profiles, reveal = sim.run(a.try_, seed=1)
        prof = profiles[-1]["data"]
        o = Oracle(cfg)
        o.visitor_id = prof["visitor_id"]
        complete = http_complete(dict(DEFAULTS, **cfg))
        from . import voice
        for kind, msgs, n in (("words", voice.words_messages(prof), DEFAULTS["words_tokens"]),
                              ("dossier", voice.dossier_messages(prof), DEFAULTS["dossier_tokens"])):
            t0 = time.time()
            try:
                text = complete(msgs, n)
            except Exception as e:
                print("model not reachable at", a.url, "-", e)
                print("fallback (profiler template):", reveal["data"]["lines"][:4])
                return 1
            print("== {} ({:.1f}s)\n{}\n-> {}".format(kind, time.time() - t0, text,
                                                     o.accept(kind, o.visitor_id, text)))
        return 0
    if a.ws:
        return run_forever(a.ws, cfg, debug=a.debug)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
