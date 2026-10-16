"""Read-only posture: the single source of truth for the guard's on/off switch.

Every surface reads and writes ONE file under HERMES_HOME, so the switch works
no matter which one flips it:

- the agent half (``__init__.py``) reads it on every tool call
- the ``/readonly`` slash command writes it
- the dashboard backend (``dashboard/plugin_api.py``) reads/writes it for the
  desktop chip

Missing state file means read-only is OFF only if the user turned it off; a
fresh install that never wrote the file defaults to ON (fail-safe: the plugin
exists to restrict, so the surprising default must be the restrictive one).
An unreadable or corrupt file is treated as ON.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

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
        return {"enabled": True, "error": "unreadable state file"}


def read_only_enabled() -> bool:
    """True = the guard blocks every non-read-only tool call."""
    return bool(_read_raw().get("enabled", True))


def set_read_only(enabled: bool, source: str = "unknown") -> dict:
    """Write the switch. Returns the new state dict."""
    payload = {
        "enabled": bool(enabled),
        "updated_at": time.time(),
        "updated_by": source,
    }
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(path)  # atomic: a reader never sees a half-written file
    return payload


def status() -> dict:
    return {"enabled": read_only_enabled(), "state_file": str(state_path())}
