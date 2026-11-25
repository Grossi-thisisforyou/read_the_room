"""Opt-in face recognition for booked guests. Off unless a guest file says consent.face is true."""
from .core import Recogniser, enrol, load_enrolled  # noqa: F401
