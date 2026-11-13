"""INFINITE JEST sound engine: adaptive dark industrial techno.

    from infinite_jest import audio
    eng = audio.create(config)
    eng.start(); eng.on_state(state); eng.on_sensor(data); eng.on_wipe(); eng.stop()
"""
from .engine import AudioEngine


def create(config=None):
    return AudioEngine(config or {})


__all__ = ["create", "AudioEngine"]
