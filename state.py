"""Mode state: the single source of truth for the guard's posture.

Three mutually exclusive modes live in ONE file under HERMES_HOME, so the switch
works no matter which surface flips it:

- ``readonly``  — every non-inspection tool call is blocked.
- ``plan``      — read-only, plus a per-turn directive to plan instead of
                  execute. The only write allowed is a plan markdown file under
                  ``.hermes/plans/``.
- ``writable``  — nothing is blocked.

Fail-safe default: a missing, unreadable, or unrecognised state file reads as
``readonly``. The plugin exists to restrict, so the surprising default must be
the restrictive one.

A 1.x file (before modes existed) stored only ``enabled``, where ``True`` meant
"writes blocked". ``read_mode`` migrates it on read, and ``set_mode`` keeps
writing that key so nothing else reading the file breaks.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

MODE_READONLY = "readonly"
MODE_PLAN = "plan"
MODE_WRITABLE = "writable"

#: Every valid mode, most restrictive first. The order is also the toggle cycle.
MODES: tuple[str, ...] = (MODE_READONLY, MODE_PLAN, MODE_WRITABLE)

#: What a missing or unreadable state file reads as.
DEFAULT_MODE = MODE_READONLY

STATE_FILENAME = "readonly-guard.state"


def state_path() -> Path:
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(home) / STATE_FILENAME


def _read_raw() -> dict:
    try:
        return json.loads(state_path().read_text())
    except FileNotFoundError:
        return {}
    except Exception:
        return {"mode": MODE_READONLY, "error": "unreadable state file"}


def read_mode() -> str:
    """The current mode. Anything unrecognised reads as the restrictive default."""
    raw = _read_raw()
    value = str(raw.get("mode", "")).strip().lower()
    if value in MODES:
        return value
    if "mode" not in raw and raw.get("enabled") is False:
        return MODE_WRITABLE  # a 1.x file the user had switched off
    return DEFAULT_MODE


def blocks_writes(mode: str | None = None) -> bool:
    """True while the guard is restricting tool calls (readonly or plan)."""
    return (mode or read_mode()) != MODE_WRITABLE


def set_mode(mode: str, source: str = "unknown") -> dict:
    """Write the mode. Returns the new state dict. Raises ValueError on an unknown mode."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")
    payload = {
        "mode": mode,
        # Kept for readers of the 1.x key: True meant "writes blocked".
        "enabled": mode != MODE_WRITABLE,
        "updated_at": time.time(),
        "updated_by": source,
    }
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)  # atomic: a reader never sees a half-written file
    return payload


def next_mode(mode: str | None = None) -> str:
    """The mode a ``toggle`` advances to: readonly -> plan -> writable -> readonly."""
    current = mode or read_mode()
    try:
        return MODES[(MODES.index(current) + 1) % len(MODES)]
    except ValueError:
        return DEFAULT_MODE


def status() -> dict:
    mode = read_mode()
    return {
        "mode": mode,
        "blocking": blocks_writes(mode),
        "modes": list(MODES),
        "state_file": str(state_path()),
    }
