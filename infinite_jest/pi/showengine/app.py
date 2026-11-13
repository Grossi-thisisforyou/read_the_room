"""The runner: starts the hub, loads the modules, opens the projector, loops.

The frame loop and the network share one asyncio loop, so there are no threads
to go wrong. Each frame: tick the engine, draw the visuals, flip. Keys on a
keyboard plugged into the Pi (or the laptop): Esc quit, D debug overlay,
N next phase, W wipe, B blackout.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import Any

from . import plugins, protocol as P
from .engine import Engine
from .hub import Hub

log = logging.getLogger("showengine.app")


def _pick_video_driver(cfg: dict) -> None:
    """On Pi OS Lite there is no desktop: draw straight to the HDMI output (KMS/DRM)."""
    if os.environ.get("SDL_VIDEODRIVER"):
        return
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"


def load_modules(cfg: dict, size: tuple[int, int] | None, want_audio: bool) -> tuple[Any, Any, Any]:
    mods = cfg["modules"]
    fallbacks = mods.get("use_fallbacks", True)
    visuals = audio = profiler = None
    if size is not None:
        mod = plugins.load(mods.get("visuals"))
        if mod is not None:
            visuals = plugins.call(mod, "create", size, cfg.get("visuals", {}))
        if visuals is None and fallbacks:
            from .outputs import fallback_visuals
            visuals = fallback_visuals.create(size, cfg.get("visuals", {}))
            log.info("visuals: built-in fallback")
        else:
            log.info("visuals: %s", mods.get("visuals"))
    if want_audio:
        mod = plugins.load(mods.get("audio"))
        if mod is not None:
            audio = plugins.call(mod, "create", cfg.get("audio", {}))
        if audio is None and fallbacks:
            from .outputs import fallback_audio
            audio = fallback_audio.create(cfg.get("audio", {}))
            log.info("audio: built-in fallback")
        else:
            log.info("audio: %s", mods.get("audio"))
        plugins.call(audio, "start")
    if mods.get("profiler_in_process", True):
        mod = plugins.load(mods.get("profiler"))
        if mod is not None:
            profiler = plugins.call(mod, "create", cfg.get("profiler", {}))
            log.info("profiler: %s (in process)", mods.get("profiler"))
    if profiler is None:
        log.info("profiler: none in process (a profiler can still connect over /ws; fallback guesses otherwise)")
    return visuals, audio, profiler


class Runner:
    def __init__(self, cfg: dict, simulate: bool = False, audio: bool = True):
        self.cfg = cfg
        self.simulate = simulate
        self.want_audio = audio
        self.running = True
        self.debug = bool(cfg["display"].get("show_debug"))
        self.screen = None
        self.font = None

    def _open_display(self) -> tuple[int, int] | None:
        d = self.cfg["display"]
        if not d.get("enabled", True):
            return None
        _pick_video_driver(self.cfg)
        try:
            import pygame
            pygame.display.init()       # not pygame.init(): leave the sound card to the audio module
            pygame.font.init()
            if d.get("fullscreen", True):
                self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.screen = pygame.display.set_mode((int(d["width"]), int(d["height"])))
            pygame.display.set_caption("Infinite Jest")
            pygame.mouse.set_visible(False)
            self.font = pygame.font.Font(None, 28)
            log.info("display %dx%d via %s", *self.screen.get_size(), pygame.display.get_driver())
            return self.screen.get_size()
        except Exception as e:
            log.error("no display (%s); running without picture", e)
            self.screen = None
            return None

    def _events(self, engine: Engine) -> None:
        import pygame
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.KEYDOWN:
                ctl = {pygame.K_n: "next", pygame.K_w: "wipe", pygame.K_b: "blackout"}.get(ev.key)
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    self.running = False
                elif ev.key == pygame.K_d:
                    self.debug = not self.debug
                elif ctl:
                    engine.handle(P.make(P.CONTROL, {"cmd": ctl}), "control")

    def _overlay(self, engine: Engine, hub: Hub) -> None:
        s = engine.state
        lines = [
            f"{s['phase']}  {s['phase_t']:.0f}s   scene {s['scene']}   hook {s['hook'] or '-'}",
            f"intensity {s['intensity']:.2f}   tempo {s['tempo']:.0f}   presence {engine.presence.score:.2f}"
            f"{' ON' if engine.presence.present else ''}",
            f"fps {hub.fps:.0f}   clients {len(hub.clients)}   sensors {engine.stats['sensor']}   frames {engine.stats['frame']}",
        ]
        y = 12
        for line in lines:
            img = self.font.render(line, True, (230, 200, 60), (0, 0, 0))
            self.screen.blit(img, (12, y))
            y += img.get_height() + 4

    async def _simulate(self, engine: Engine) -> None:
        from .sim import visitors
        async for msg in visitors():
            engine.handle(msg, "phone")

    async def run(self) -> None:
        size = self._open_display()
        visuals, audio, profiler = load_modules(self.cfg, size, self.want_audio)
        engine = Engine(self.cfg, visuals=visuals, audio=audio, profiler=profiler)
        hub = Hub(engine, self.cfg)
        await hub.start()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except (NotImplementedError, RuntimeError):
                pass
        sim_task = asyncio.ensure_future(self._simulate(engine)) if self.simulate else None
        if self.simulate:
            log.info("simulating visitors")

        fps = float(self.cfg["display"].get("fps", 30))
        period = 1.0 / fps if self.screen is not None else 0.05
        last = time.monotonic()
        frames, fps_t = 0, last
        try:
            import pygame
            while self.running:
                now = time.monotonic()
                dt, last = now - last, now
                engine.tick(now)
                if self.screen is not None:
                    self._events(engine)
                    if engine.blackout:
                        self.screen.fill((0, 0, 0))
                    elif visuals is not None:
                        plugins.call(visuals, "render", self.screen, dt)
                    if self.debug:
                        self._overlay(engine, hub)
                    pygame.display.flip()
                frames += 1
                if now - fps_t >= 2.0:
                    hub.fps, frames, fps_t = frames / (now - fps_t), 0, now
                await asyncio.sleep(max(0.0, period - (time.monotonic() - now)))
        finally:
            if sim_task:
                sim_task.cancel()
            engine.machine.wipe()                 # nothing survives a shutdown either
            plugins.call(audio, "stop")
            await hub.stop()
            if self.screen is not None:
                pygame.display.quit()
            log.info("stopped")

    def stop(self) -> None:
        self.running = False
