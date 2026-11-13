"""Run the profiler.

    python3 -m infinite_jest.profiler --sim performer     # rehearse offline
    python3 -m infinite_jest.profiler --sim all
    python3 -m infinite_jest.profiler --ws ws://192.168.1.10:8765/ws
"""

import argparse
import json
import sys

from . import sim


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m infinite_jest.profiler")
    ap.add_argument("--sim", help="simulate a visitor: " + ", ".join(sim.ARCHETYPES) + " or all")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ws", help="engine WebSocket url, e.g. ws://192.168.1.10:8765/ws")
    ap.add_argument("--debug", action="store_true", help="print each profile (counts only, no frames)")
    args = ap.parse_args(argv)
    if args.sim:
        names = list(sim.ARCHETYPES) if args.sim == "all" else [args.sim]
        for name in names:
            print("== simulated visitor:", name, "(hidden favourite:", sim.ARCHETYPES[name]["favourite"] + ")")
            _profiles, reveal = sim.run(name, seed=args.seed, verbose=True)
            if reveal:
                print("-- reveal --")
                for line in reveal["data"]["lines"]:
                    print("   " + line)
            print()
        return 0
    if args.ws:
        from .ws_client import run_forever
        return run_forever(args.ws, debug=args.debug)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
