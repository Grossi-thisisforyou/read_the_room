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

from . import plugins, protocol as P, sdnotify
from .engine import Engine
from .hub import Hub

log = logging.getLogger("showengine.app")


def _pick_video_driver(cfg: dict) -> None:
    """On Pi OS Lite there is no desktop: draw straight to the HDMI output (KMS/DRM)."""
    if os.environ.get("SDL_VIDEODRIVER"):
        return
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"


def load_visuals(cfg: dict, size: tuple[int, int]) -> Any:
    mods = cfg["modules"]
    visuals = None
    mod = plugins.load(mods.get("visuals"))
    if mod is not None:
        visuals = plugins.call(mod, "create", size, cfg.get("visuals", {}))
    if visuals is None and mods.get("use_fallbacks", True):
        from .outputs import fallback_visuals
        visuals = fallback_visuals.create(size, cfg.get("visuals", {}))
        log.info("visuals: built-in fallback")
    else:
        log.info("visuals: %s", mods.get("visuals"))
    return visuals


def load_modules(cfg: dict, size: tuple[int, int] | None, want_audio: bool) -> tuple[Any, Any, Any]:
    mods = cfg["modules"]
    fallbacks = mods.get("use_fallbacks", True)
    visuals = audio = profiler = None
    if size is not None and str(cfg.get("show", "duet")) != "duet":
        visuals = load_visuals(cfg, size)
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
        self.engine: Engine | None = None
        self.display_retry = float(cfg["display"].get("retry_s", 5.0))
        self._next_display_try = 0.0
        self._hdmi_was: bool | None = None
        self.screen2 = None
        self.show = str(cfg.get("show", "duet"))
        self.duet = None
        if self.show == "duet":
            # two screens: TV (channel 1) = the face, projector (channel 2) = the wall
            for k, v in (("max_visit", 300.0), ("release_time", 40.0), ("wipe_time", 8.0)):
                cfg.setdefault("visit", {}).setdefault(k, v)
            cfg["speak"] = False             # the duet speaks for itself, only once the TV is on
            d = cfg.get("duet") if isinstance(cfg.get("duet"), dict) else {}
            cfg["display"]["main_display"] = int(d.get("tv_display", cfg["display"].get("main_display", 0)))
        elif cfg["display"].get("second_screen", True) and cfg["display"].get("enabled", True):
            from .second_screen import SecondScreen
            self.screen2 = SecondScreen(int(cfg["display"].get("second_display", 1)),
                                        float(cfg["display"].get("second_fps", 10)))

    def _open_display(self) -> tuple[int, int] | None:
        d = self.cfg["display"]
        if not d.get("enabled", True):
            return None
        _pick_video_driver(self.cfg)
        try:
            import pygame
            pygame.display.quit()       # forget the last attempt: re-probe the outputs
            pygame.display.init()       # not pygame.init(): leave the sound card to the audio module
            pygame.font.init()
            if d.get("fullscreen", True):
                # exactly the configured mode (1920x1080 by default), not whatever the projector reports
                self.screen = pygame.display.set_mode((int(d["width"]), int(d["height"])), pygame.FULLSCREEN,
                                                      display=int(d.get("main_display", 0)))
            else:
                self.screen = pygame.display.set_mode((int(d["width"]), int(d["height"])))
            pygame.display.set_caption("Infinite Jest")
            pygame.mouse.set_visible(False)
            self.font = pygame.font.Font(None, 28)
            log.info("display %dx%d via %s", *self.screen.get_size(), pygame.display.get_driver())
            if self.screen2 is not None:
                self.screen2.reset()            # pygame.display was re-initialised: open it again
            return self.screen.get_size()
        except Exception as e:
            plugins.report(log, "display", f"no display ({e}); running without picture, "
                           f"trying again every {self.display_retry:.0f} s", exc_info=False)
            self.screen = None
            return None

    def _lost_display(self, why: str) -> None:
        plugins.report(log, "display-lost", f"display lost ({why}); trying to reopen it", exc_info=False)
        self.screen = None
        self._next_display_try = time.monotonic() + self.display_retry

    def _retry_display(self, engine: Engine, now: float) -> None:
        """Projector switched on after the Pi, or plugged back in: open it again."""
        if now < self._next_display_try or not self.cfg["display"].get("enabled", True):
            return
        self._next_display_try = now + self.display_retry
        size = self._open_display()
        if size is None:
            return
        log.info("display is back")
        if engine.visuals is None and self.duet is None:
            engine.visuals = load_visuals(self.cfg, size)

    def _hdmi_reconnected(self, now: float) -> bool:
        """KMS/DRM keeps 'drawing' to an unplugged HDMI and may stay black when it comes
        back; watch the connector and reopen the display when it is plugged in again."""
        status = hdmi_status()
        was, self._hdmi_was = self._hdmi_was, status
        return was is False and status is True

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
        sdnotify.notify("WATCHDOG=1")
        visuals, audio, profiler = load_modules(self.cfg, size, self.want_audio)
        sdnotify.notify("WATCHDOG=1")
        engine = self.engine = Engine(self.cfg, visuals=visuals, audio=audio, profiler=profiler)
        if self.show == "duet":
            from .duet import Duet, WallScreen
            self.duet = Duet(self.cfg, engine)
            engine.state_hooks.append(self.duet.update)
            d = self.cfg.get("duet") if isinstance(self.cfg.get("duet"), dict) else {}
            if self.cfg["display"].get("enabled", True):
                self.screen2 = WallScreen(self.duet, int(d.get("wall_display", 1)), float(d.get("wall_screen_fps", 30)))
            engine.extra_status = self.duet.status
            self.duet.start()
        hub = Hub(engine, self.cfg)
        await hub.start()
        sdnotify.notify("READY=1")

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
        last = time.monotonic()
        frames, fps_t, dog_t = 0, last, 0.0
        self._next_display_try = last + self.display_retry
        try:
            import pygame
            while self.running:
                now = time.monotonic()
                dt, last = now - last, now
                try:
                    engine.tick(now)
                except Exception:       # one bad tick must not take the whole room down
                    plugins.report(log, "tick", "engine tick failed")
                if self.screen is None:
                    self._retry_display(engine, now)
                elif now - dog_t >= 2.0 and self._hdmi_reconnected(now):
                    self._lost_display("HDMI unplugged and plugged back in")
                    self._next_display_try = now
                if self.screen is not None:
                    try:
                        self._events(engine)
                        if engine.blackout:
                            self.screen.fill((0, 0, 0))
                        elif self.duet is not None:
                            wall_here = self.screen2 is None or self.screen2.failed
                            self.duet.draw_tv(self.screen, now, wall_here=wall_here)
                        elif engine.visuals is not None:
                            plugins.call(engine.visuals, "render", self.screen, dt)
                        if self.debug:
                            self._overlay(engine, hub)
                        pygame.display.flip()
                    except pygame.error as e:
                        self._lost_display(str(e))
                    if self.screen2 is not None and self.screen is not None:
                        self.screen2.update(engine.state, lambda: self._status2(engine, hub), now)
                frames += 1
                hub.last_frame_ts = time.time()
                if now - fps_t >= 2.0:
                    hub.fps, frames, fps_t = frames / (now - fps_t), 0, now
                if now - dog_t >= 2.0:
                    dog_t = now
                    sdnotify.notify("WATCHDOG=1")
                period = 1.0 / fps if self.screen is not None else 0.05
                await asyncio.sleep(max(0.0, period - (time.monotonic() - now)))
        finally:
            sdnotify.notify("STOPPING=1")
            if sim_task:
                sim_task.cancel()
            engine.machine.wipe()                 # nothing survives a shutdown either
            if self.duet is not None:
                self.duet.stop()
            plugins.call(audio, "stop")
            await hub.stop()
            if self.screen is not None:
                pygame.display.quit()
            log.info("stopped")

    @staticmethod
    def _status2(engine: Engine, hub: Hub) -> dict:
        roles: dict[str, int] = {}
        for r in hub.clients.values():
            roles[r] = roles.get(r, 0) + 1
        return {**engine.status(), "fps": round(hub.fps, 1), "clients": roles}

    def status_extra(self) -> dict:
        return self.duet.status() if self.duet is not None else {}

    def stop(self) -> None:
        self.running = False


DRM_DIR = "/sys/class/drm"


def hdmi_status(drm_dir: str = DRM_DIR) -> bool | None:
    """True if any HDMI connector reports a screen, False if all report none, None if unknown."""
    try:
        names = [n for n in os.listdir(drm_dir) if "-HDMI-" in n]
    except OSError:
        return None
    seen = []
    for n in names:
        try:
            with open(os.path.join(drm_dir, n, "status")) as f:
                seen.append(f.read().strip() == "connected")
        except OSError:
            continue
    return any(seen) if seen else None
