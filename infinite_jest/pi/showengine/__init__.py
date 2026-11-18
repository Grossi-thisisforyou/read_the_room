"""Infinite Jest show engine for the Raspberry Pi.

Runs the whole installation unattended: hosts the local message hub, reads the
phone's sensors, notices when someone walks in, runs one visit per person
(idle, approach, profiling, hook, release, wipe) and drives the projector and
the speaker. Everything a visitor leaves behind lives in memory only and is
wiped when they go.
"""

__version__ = "0.1.0"
