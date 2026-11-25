"""python3 -m showengine [options]   (run from infinite_jest/pi/)

Examples
  python3 -m showengine                       # the show, as systemd starts it on the Pi
  python3 -m showengine --windowed --simulate # on a laptop: fake visitors, a window
  python3 -m showengine --headless --simulate # no picture, no sound: watch /status or the control page
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os

from . import config


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="showengine", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.environ.get("IJ_CONFIG", "~/.config/infinite-jest/engine.toml"),
                    help="TOML settings file (default %(default)s)")
    ap.add_argument("--windowed", action="store_true", help="a window instead of fullscreen")
    ap.add_argument("--size", default=None, help="window size, e.g. 1280x720")
    ap.add_argument("--headless", action="store_true", help="no picture at all")
    ap.add_argument("--no-audio", action="store_true", help="no sound")
    ap.add_argument("--simulate", action="store_true", help="fake visitors instead of the phone")
    ap.add_argument("--port", type=int, default=None, help="HTTP/WebSocket port (default 8765)")
    ap.add_argument("--debug", action="store_true", help="debug overlay and verbose log")
    a = ap.parse_args(argv)

    over: dict = {"display": {}, "network": {}}
    if a.windowed:
        over["display"]["fullscreen"] = False
    if a.size:
        w, h = a.size.lower().split("x")
        over["display"].update(width=int(w), height=int(h))
    if a.headless:
        over["display"]["enabled"] = False
    if a.port:
        over["network"]["port"] = a.port
    if a.debug:
        over["display"]["show_debug"] = True
        over["log_level"] = "DEBUG"

    cfg = config.load(a.config, over)
    logging.basicConfig(level=getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")
    from .app import Runner
    asyncio.run(Runner(cfg, simulate=a.simulate, audio=not a.no_audio).run())


if __name__ == "__main__":
    main()
