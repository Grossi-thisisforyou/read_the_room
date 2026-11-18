"""INFINITE JEST visuals module. The show engine calls create(size, config)."""


def create(size, config=None):
    from .engine import Visuals
    return Visuals(size, config or {})
