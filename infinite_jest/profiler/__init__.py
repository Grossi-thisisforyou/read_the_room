"""INFINITE JEST audience profiler: sensor messages in, OCEAN profile out.

    from infinite_jest.profiler import create
    p = create({"seed": 1})
    replies = p.handle({"type": "sensor", "ts": 0.0, "data": {...}})

See README.md. Pure standard library; OpenCV is optional (face boxes, jpeg).
"""

from .core import Profiler, create  # noqa: F401

__all__ = ["Profiler", "create"]
