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


def call(obj: Any, method: str, *args: Any) -> Any:
    """Call an optional method on a plugin; a crash in a plugin never stops the show."""
    fn = getattr(obj, method, None) if obj is not None else None
    if fn is None:
        return None
    try:
        return fn(*args)
    except Exception:
        log.exception("%s.%s failed", type(obj).__name__, method)
        return None
