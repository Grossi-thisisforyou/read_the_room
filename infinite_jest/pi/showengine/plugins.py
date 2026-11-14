"""Find the sibling modules (visuals, audio, profiler) and fall back gracefully.

They live next to this folder in the repo: infinite_jest/visuals/, .../audio/,
.../profiler/. Each exposes `create(...)`. If one is missing or crashes on
import, the engine logs it and carries on with its built-in fallback, so the
show always plays.
"""
from __future__ import annotations

import importlib
import logging
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("showengine.plugins")

REPO_ROOT = Path(__file__).resolve().parents[3]


def _ensure_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def load(module_name: str | None) -> Any | None:
    if not module_name:
        return None
    _ensure_path()
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        log.info("module %s not installed (%s)", module_name, e.name)
        return None
    except Exception:
        log.exception("module %s failed to import", module_name)
        return None
    if not hasattr(mod, "create"):
        log.warning("module %s has no create(); ignoring", module_name)
        return None
    return mod


_last_report: dict[str, list] = {}   # key -> [monotonic time of last log, errors since]
REPORT_EVERY = 60.0


def report(logger: logging.Logger, key: str, text: str, exc_info: bool = True, level: int = logging.ERROR) -> None:
    """Log an error at most once a minute per key (with the count of the ones skipped).

    A plugin that throws on every frame would otherwise write ~30 tracebacks a
    second to the journal, for days, on an SD card.
    """
    now = time.monotonic()
    rec = _last_report.get(key)
    if rec is not None and now - rec[0] < REPORT_EVERY:
        rec[1] += 1
        return
    skipped = rec[1] if rec is not None else 0
    if len(_last_report) < 256 or rec is not None:
        _last_report[key] = [now, 0]
    more = f" (and {skipped} more times in the last minute)" if skipped else ""
    logger.log(level, "%s%s", text, more, exc_info=exc_info)


def call(obj: Any, method: str, *args: Any) -> Any:
    """Call an optional method on a plugin; a crash in a plugin never stops the show."""
    fn = getattr(obj, method, None) if obj is not None else None
    if fn is None:
        return None
    try:
        return fn(*args)
    except Exception:
        name = f"{type(obj).__name__}.{method}"
        report(log, name, f"{name} failed")
        return None
