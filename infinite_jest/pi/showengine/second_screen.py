"""The second screen: HDMI 1 shows the machine's side of the room.

A dark-data readout of what the room is sensing right now: microphone level,
motion, tilt, the phase, the OCEAN guess building up, and the words / dossier
lines already on the wall. Same privacy rules as the wall: only what the state
already carries (no frames, no ids beyond the random visit code, no typed text).

Opened with pygame's SDL2 window API on display index 1. If there is no second
display, or SDL refuses, it logs once and the show carries on with one screen.
Drawn at about 10 fps so it never slows the projector.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

log = logging.getLogger("showengine.screen2")

BG = (6, 6, 6)
DIM = (90, 90, 90)
BONE = (232, 226, 208)
RED = (192, 57, 43)
GOLD = (232, 197, 71)
TRAITS = (("O", "OPENNESS"), ("C", "CONSCIENTIOUSNESS"), ("E", "EXTRAVERSION"),
          ("A", "AGREEABLENESS"), ("N", "NEUROTICISM"))


class SecondScreen:
    def __init__(self, display_index: int = 1, fps: float = 10.0):
        self.index = display_index
        self.period = 1.0 / max(1.0, fps)
        self.window = None
        self.renderer = None
        self.surface = None
        self.size = (0, 0)
        self.failed = False
        self._next = 0.0
        self._hist = {k: deque(maxlen=240) for k in ("level", "motion", "tilt", "intensity")}
        self._fonts: dict[int, Any] = {}

    # ------------------------------------------------------------------ open
    def open(self) -> bool:
        if self.window is not None:
            return True
        if self.failed:
            return False
        try:
            import pygame
            from pygame._sdl2 import video
            sizes = pygame.display.get_desktop_sizes()
            if len(sizes) <= self.index:
                log.info("second screen: only %d display(s) found; one screen it is", len(sizes))
                self.failed = True
                return False
            self.size = tuple(sizes[self.index])
            pos = 0x2FFF0000 | self.index          # SDL_WINDOWPOS_CENTERED_DISPLAY(index)
            self.window = video.Window("Infinite Jest data", size=self.size, position=(pos, pos),
                                       fullscreen=True)
            try:
                self.renderer = video.Renderer(self.window)
            except Exception:
                self.renderer = None                # software path: draw into the window surface
            self.surface = pygame.Surface(self.size)
            log.info("second screen %dx%d on display %d (%s)", *self.size, self.index,
                     "renderer" if self.renderer else "surface")
            return True
        except Exception as e:
            log.warning("second screen unavailable (%s); carrying on with one screen", e)
            self.close()
            self.failed = True
            return False

    def close(self) -> None:
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:
            pass
        self.window = self.renderer = self.surface = None

    def reset(self) -> None:
        """Called when the main display is reopened (pygame.display re-initialised)."""
        self.close()
        self.failed = False

    # ------------------------------------------------------------------ draw
    def update(self, state: dict, status, now: float | None = None) -> None:
        """status: a dict, or a function returning one (only called when a frame is due)."""
        now = time.monotonic() if now is None else now
        if now < self._next or not self.open():
            return
        self._next = now + self.period
        try:
            if callable(status):
                status = status()
            self._record(state)
            self._draw(self.surface, state, status)
            self._present()
        except Exception as e:
            log.warning("second screen failed (%s); closing it", e)
            self.close()
            self.failed = True

    def _present(self) -> None:
        if self.renderer is not None:
            from pygame._sdl2 import video
            tex = video.Texture.from_surface(self.renderer, self.surface)
            self.renderer.clear()
            tex.draw()
            self.renderer.present()
        else:
            ws = self.window.get_surface()
            ws.blit(self.surface, (0, 0))
            self.window.flip()

    def _font(self, px: int):
        import pygame
        f = self._fonts.get(px)
        if f is None:
            f = self._fonts[px] = pygame.font.Font(None, px)
        return f

    def _text(self, surf, txt: str, pos, px: int, col=BONE):
        img = self._font(px).render(str(txt), True, col)
        surf.blit(img, pos)
        return img.get_height()

    def _record(self, st: dict) -> None:
        s = st.get("sensor") or {}
        audio = s.get("audio") if isinstance(s.get("audio"), dict) else {}
        level = s.get("loudness", audio.get("level", 0)) or 0
        self._hist["level"].append(float(level) if isinstance(level, (int, float)) else 0.0)
        m = s.get("motion", 0) or 0
        self._hist["motion"].append(float(m) if isinstance(m, (int, float)) else 0.0)
        tilt = (st.get("tilt") or {}).get("energy", 0) or 0
        self._hist["tilt"].append(float(tilt))
        self._hist["intensity"].append(float(st.get("intensity", 0) or 0))

    def _graph(self, surf, rect, values, col, label: str, px: int):
        import pygame
        x, y, w, h = rect
        pygame.draw.rect(surf, (24, 24, 24), rect, 1)
        self._text(surf, label, (x + 8, y + 6), px, DIM)
        vals = list(values)
        if len(vals) >= 2:
            step = w / (len(vals) - 1)
            pts = [(x + i * step, y + h - 4 - v * (h - 10)) for i, v in enumerate(vals)]
            pygame.draw.lines(surf, col, False, pts, 2)
            self._text(surf, f"{vals[-1]:.3f}", (x + w - 90, y + 6), px, col)

    def _draw(self, surf, st: dict, status: dict) -> None:
        import pygame
        w, h = surf.get_size()
        u = h / 1080.0
        px_s, px_m, px_l = int(24 * u), int(34 * u), int(84 * u)
        surf.fill(BG)
        if st.get("blackout"):
            return
        m = int(40 * u)
        # header
        phase = str(st.get("phase", "idle")).upper()
        self._text(surf, "INFINITE JEST // ROOM TELEMETRY", (m, m), px_s, RED)
        self._text(surf, phase, (m, m + int(30 * u)), px_l, BONE)
        sub = f"T+{float(st.get('phase_t', 0)):5.1f}s   SUBJECT {st.get('visitor_id') or '----'}   " \
              f"VISITS {status.get('counts', {}).get('visits', 0)}   {time.strftime('%H:%M:%S')}"
        self._text(surf, sub, (m, m + int(115 * u)), px_s, DIM)

        # live signals, left column
        gx, gy, gw, gh = m, int(200 * u), int(w * 0.46), int(150 * u)
        for i, (key, col, label) in enumerate((("level", GOLD, "MICROPHONE LEVEL"), ("motion", BONE, "MOTION"),
                                               ("tilt", RED, "HANDLING"), ("intensity", DIM, "DRIVE"))):
            self._graph(surf, (gx, gy + i * (gh + int(16 * u)), gw, gh), self._hist[key], col, label, px_s)

        # profile, right column
        rx, ry = int(w * 0.54), int(200 * u)
        rw = w - rx - m
        sealed = bool(st.get("discreet"))
        self._text(surf, "PROFILE  SEALED UNTIL THE END" if sealed else "PROFILE (GUESSED, NOT KNOWN)", (rx, ry), px_s,
                   RED if sealed else DIM)
        ocean = {} if sealed else (st.get("ocean") or {})
        conf = float(st.get("confidence", 0) or 0)
        for i, (k, name) in enumerate(TRAITS):
            y = ry + int(40 * u) + i * int(52 * u)
            v = ocean.get(k)
            self._text(surf, name, (rx, y), px_s, BONE)
            bar = pygame.Rect(rx, y + int(24 * u), rw - int(110 * u), int(14 * u))
            pygame.draw.rect(surf, (30, 30, 30), bar)
            if sealed:
                # the reading is happening, but it isn't shown: a redaction that fills as it builds
                b = float(st.get("build", 0) or 0)
                pygame.draw.rect(surf, (52, 52, 52), (bar.x, bar.y, int(bar.w * b), bar.h))
                self._text(surf, "####", (bar.right + int(14 * u), y + int(14 * u)), px_s, DIM)
            elif isinstance(v, (int, float)):
                pygame.draw.rect(surf, RED, (bar.x, bar.y, int(bar.w * max(0, min(1, v))), bar.h))
                self._text(surf, f"{v:.3f}", (bar.right + int(14 * u), y + int(14 * u)), px_s, BONE)
            else:
                self._text(surf, "----", (bar.right + int(14 * u), y + int(14 * u)), px_s, DIM)
        y = ry + int(40 * u) + 5 * int(52 * u) + int(10 * u)
        if not sealed:
            self._text(surf, f"CONFIDENCE {conf:.2f}   SOURCE {st.get('profile_source') or '-'}", (rx, y), px_s, GOLD)
        else:
            self._text(surf, f"READING {int(100 * float(st.get('build', 0) or 0))}%", (rx, y), px_s, GOLD)

        # words / dossier / reveal lines
        y += int(50 * u)
        lines: list[str] = []
        rv = st.get("reveal") or {}
        if isinstance(rv.get("lines"), list):
            struck = int(rv.get("struck", 0) or 0)
            n = len(rv["lines"])
            lines = [("~ " if i >= n - struck else "") + str(x) for i, x in enumerate(rv["lines"])]
        else:
            lines = [str(x) for x in (st.get("dossier") or [])] + [str(x) for x in (st.get("words") or [])]
        if st.get("big_line"):
            lines.insert(0, str(st["big_line"]))
        self._text(surf, "FILE", (rx, y), px_s, DIM)
        y += int(32 * u)
        maxc = max(20, int(rw / (px_m * 0.42)))
        for line in lines[-14:]:
            if y > h - m - px_m:
                break
            col = DIM if line.startswith("~ ") else BONE
            self._text(surf, line[:maxc], (rx, y), px_m, col)
            if line.startswith("~ "):
                pygame.draw.line(surf, RED, (rx, y + px_m // 3), (rx + min(rw, len(line) * px_m * 0.42), y + px_m // 3), 2)
            y += int(px_m * 1.1)

        # footer
        clients = status.get("clients", {})
        foot = (f"FPS {status.get('fps', 0)}   SENSORS {status.get('counts', {}).get('sensor', 0)}   "
                f"FRAMES {status.get('counts', {}).get('frame', 0)}   CLIENTS {sum(clients.values()) if clients else 0}   "
                "NOTHING IS STORED. EVERY VISIT IS DELETED.")
        self._text(surf, foot, (m, h - m), px_s, DIM)
