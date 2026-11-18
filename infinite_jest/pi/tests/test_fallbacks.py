"""Headless tests for the built-in fallback visuals and audio.

Run from infinite_jest/pi:  SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy pytest -q tests
"""
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pygame  # noqa: E402
import pytest  # noqa: E402

from showengine.outputs import fallback_audio, fallback_visuals  # noqa: E402

W, H = 1280, 720
OCEAN = {"O": 0.8, "C": 0.3, "E": 0.55, "A": 0.2, "N": 0.9}
SEQUENCE = [
    {"phase": "idle"},
    {"phase": "approach", "visitor_id": "v-7f3a", "intensity": 0.3, "tempo": 120},
    {"phase": "profiling", "visitor_id": "v-7f3a", "scene": "dossier", "intensity": 0.5, "ocean": OCEAN},
    {"phase": "hook", "visitor_id": "v-7f3a", "scene": "flesh", "intensity": 0.9, "tempo": 138,
     "palette": {"name": "meat", "colors": ["#0a0505", "#7a0a0a", "#d98c8c", "#f0e6d0"]}},
    {"phase": "hook", "visitor_id": "v-7f3a", "scene": "scrawl", "intensity": 1.0, "hook": "longing",
     "palette": {"name": "crown", "colors": ["#000000", "#f2c200", "#c81818", "#ffffff"]}},
    {"phase": "hook", "visitor_id": "v-7f3a", "scene": "inverted", "intensity": 0.6},
    {"phase": "hook", "visitor_id": "v-7f3a", "scene": "mirror", "intensity": 0.7,
     "sensor": {"motion": 0.6, "loudness": 0.4, "faces": 2,
                "tilt": {"alpha": 90, "beta": 30, "gamma": -20}, "touch": {"x": 0.3, "y": 0.6}}},
    {"phase": "hook", "scene": "nonsense-scene", "intensity": 0.4},
    {"phase": "release", "visitor_id": "v-7f3a", "intensity": 0.2},
    {"phase": "wipe"},
    {"phase": "idle", "palette": {"colors": ["garbage", None, 5]}, "tempo": "fast", "intensity": None},
]


@pytest.fixture(scope="module", autouse=True)
def _pygame():
    pygame.init()
    yield
    pygame.quit()


def test_visuals_every_scene_renders_fast():
    vis = fallback_visuals.create((W, H), {})
    surf = pygame.Surface((W, H))
    worst = 0.0
    total, frames = 0.0, 0
    for st in SEQUENCE:
        vis.on_state(st)
        for _ in range(12):
            t0 = time.perf_counter()
            vis.render(surf, 1 / 30)
            dt = time.perf_counter() - t0
            total += dt
            frames += 1
            worst = max(worst, dt)
    for scene in fallback_visuals.SCENES:  # every scene explicitly, including erase
        vis.on_state({"scene": scene, "intensity": 0.8, "visitor_id": "v-1"})
        for _ in range(5):
            vis.render(surf, 1 / 30)
    print(f"fallback visuals: {total / frames * 1000:.1f} ms/frame avg, {worst * 1000:.1f} ms worst at {W}x{H}")
    assert total / frames < 0.1


def test_visuals_draw_something_and_wipe_ends_black():
    vis = fallback_visuals.create((W, H), {})
    surf = pygame.Surface((W, H))
    vis.on_state({"phase": "hook", "scene": "flesh", "intensity": 0.8, "visitor_id": "x"})
    for _ in range(20):
        vis.render(surf, 1 / 30)
    arr = pygame.surfarray.array3d(surf)
    assert arr.max() > 100  # flesh is visibly drawn
    assert arr[..., 0].mean() > arr[..., 2].mean()  # and it is red-leaning
    vis.on_wipe()
    vis.render(surf, 0.05)
    assert pygame.surfarray.array3d(surf).mean() > 200  # white flash
    for _ in range(40):  # 10 s later: black with fading text, almost nothing left
        vis.render(surf, 0.25)
    assert pygame.surfarray.array3d(surf).mean() < 10
    assert vis._vid is None and vis._ocean is None and vis._data_lines == []


def test_visuals_handle_resize_and_empty_state():
    vis = fallback_visuals.create((320, 180), {})
    vis.on_state({})
    vis.render(pygame.Surface((320, 180)), 0.03)
    vis.render(pygame.Surface((640, 360)), 0.03)  # engine changed size
    vis.on_state(None)
    vis.render(pygame.Surface((640, 360)), 0.0)


def test_synth_bar_is_one_bar_and_bounded():
    for phase in ("idle", "approach", "profiling", "hook", "release"):
        for tempo in (118, 142):
            x = fallback_audio.synth_bar(44100, tempo, phase, 3, seed=1)
            assert x.shape[1] == 2 and abs(x.shape[0] - 44100 * 240 / tempo) <= 32
            assert np.isfinite(x).all() and np.abs(x).max() <= 1.0
    idle = fallback_audio.synth_bar(44100, 128, "idle", 0)
    hook = fallback_audio.synth_bar(44100, 128, "hook", 4)
    assert np.sqrt((idle ** 2).mean()) < 0.5 * np.sqrt((hook ** 2).mean())


def test_audio_start_stop_under_dummy_driver():
    audio = fallback_audio.create({"volume": 0.5})
    audio.start()  # either works on the dummy driver or degrades to a no-op
    try:
        for st in SEQUENCE:
            audio.on_state(st)
            time.sleep(0.15)
        audio.on_wipe()
        time.sleep(0.1)
        if audio.active:
            assert audio._thread.is_alive()
    finally:
        audio.stop()
    assert not audio.active
    audio.stop()  # idempotent


def test_audio_degrades_without_device(monkeypatch):
    if pygame.mixer.get_init():
        pygame.mixer.quit()

    def boom(*a, **k):
        raise pygame.error("no audio device")

    monkeypatch.setattr(pygame.mixer, "init", boom)
    audio = fallback_audio.create({})
    audio.start()
    assert not audio.active
    audio.on_state({"phase": "hook", "intensity": 1.0})
    audio.on_wipe()
    audio.stop()
