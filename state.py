"""Per-session mode state: the single source of truth for the guard's posture.

Three mutually exclusive modes, held **per session** in ONE file under HERMES_HOME:

- ``readonly``  — every non-inspection tool call is blocked.
- ``plan``      — read-only, plus a per-turn directive to plan instead of execute.
                  The only write allowed is a plan markdown file under ``.hermes/plans/``.
- ``writable``  — nothing is blocked.

A session with no entry follows the plugin setting ``default_mode`` (``settings.py``),
which itself defaults to ``readonly``. The mode is per session because a machine-wide
switch lets one chat loosen the guard under every other chat that is already running.

Fail-safe by construction: a missing, unreadable, unparseable, or non-object file holds
no sessions, so every session lands on the configured default. A pre-3.0 file with a
top-level ``mode`` is ignored — that file described the machine, and nothing here may
inherit a looser posture from it.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

MODE_READONLY = "readonly"
MODE_PLAN = "plan"
MODE_WRITABLE = "writable"

#: Every valid mode, most restrictive first. The order is also the toggle cycle.
MODES: tuple[str, ...] = (MODE_READONLY, MODE_PLAN, MODE_WRITABLE)

#: What a session with no entry reads as when the setting cannot be read.
DEFAULT_MODE = MODE_READONLY

STATE_FILENAME = "readonly-guard.state"

#: Schema generation of the file. 2 = {"version": 2, "sessions": {...}}.
SCHEMA_VERSION = 2

#: Sessions kept in the table. An entry that ages out falls back to the default, which
#: is the restrictive one, so pruning can only tighten.
SESSION_CAP = 200

#: Serialises the read-modify-write of the table. Every in-process writer — the desktop
#: chip, ``/readonly``, the dashboard — shares this module, and two writes that read the
#: same table would each write it back and lose the other's session. (A ``mkstemp`` +
#: ``replace`` write is atomic for READERS; it does not make the read-modify-write atomic
#: for writers.) Cross-process writers can still lose a session, which is safe by design:
#: a lost entry falls back to the default, and the default is the restrictive one.
_WRITE_LOCK = threading.Lock()


def state_path() -> Path:
    home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(home) / STATE_FILENAME


def _read_raw() -> dict:
    """The state file as a mapping; anything else reads as empty.

    Missing, unreadable, unparseable, and parseable-but-not-an-object all collapse to
    ``{}`` so every one of them means "no sessions" rather than raising into the hook
    (which would block every tool call behind a confusing error) or into the dashboard
    (which would 500).
    """
    try:
        raw = json.loads(state_path().read_text())
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _sessions(raw: dict | None = None) -> dict[str, dict]:
    """Usable session entries: id -> entry, dropping anything whose mode is invalid."""
    source = raw if isinstance(raw, dict) else _read_raw()
    table = source.get("sessions")
    if not isinstance(table, dict):
        return {}
    return {
        str(sid): entry
        for sid, entry in table.items()
        if str(sid) and isinstance(entry, dict) and entry.get("mode") in MODES
    }


def get_session_mode(session_id: str) -> str | None:
    """This session's explicit mode, or ``None`` when it follows the default."""
    if not session_id:
        return None
    entry = _sessions().get(str(session_id))
    return str(entry["mode"]) if entry else None


def _write(payload: dict) -> None:
    """Replace the state file atomically.

    A uniquely named temp file in the same directory, then ``os.replace``, so a reader
    never sees a half-written file. The name must be unique: several sessions (and the
    desktop chip) can write at the same moment, and a shared temp name makes the loser's
    replace raise ``FileNotFoundError``.
    """
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as tmp:
            tmp.write(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def set_session_mode(session_id: str, mode: str, source: str = "unknown") -> dict:
    """Write ONE session's mode. Raises ``ValueError`` on an empty id or unknown mode.

    An empty id is a caller bug: there is no global slot to fall back to, and a silent
    machine-wide write is exactly the behaviour this file exists to remove.
    """
    if not session_id:
        raise ValueError("session_id is required; per-session state has no global slot")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {', '.join(MODES)}")
    now = time.time()
    with _WRITE_LOCK:
        table = dict(_sessions())
        table[str(session_id)] = {"mode": mode, "updated_at": now, "updated_by": source}
        if len(table) > SESSION_CAP:
            newest = sorted(table.items(), key=lambda kv: float(kv[1].get("updated_at") or 0.0))
            table = dict(newest[-SESSION_CAP:])
        payload = {"version": SCHEMA_VERSION, "sessions": table}
        _write(payload)
    return payload


def blocks_writes(mode: str | None = None) -> bool:
    """True while the guard is restricting tool calls (readonly or plan)."""
    return (mode or MODE_READONLY) != MODE_WRITABLE


def next_mode(mode: str = MODE_READONLY) -> str:
    """The mode a ``toggle`` advances to: readonly -> plan -> writable -> readonly."""
    try:
        return MODES[(MODES.index(mode) + 1) % len(MODES)]
    except ValueError:
        return DEFAULT_MODE


def status(session_id: str = "", default: str = DEFAULT_MODE) -> dict:
    """The payload every surface reads: this session's mode, and what it means.

    ``source`` is ``"session"`` when the session has its own entry and ``"default"``
    when it is following the setting — the desktop chip labels the two differently.
    """
    effective_default = default if default in MODES else DEFAULT_MODE
    explicit = get_session_mode(session_id)
    mode = explicit or effective_default
    return {
        "modes": list(MODES),
        "session": str(session_id),
        "mode": mode,
        "source": "session" if explicit else "default",
        "default": effective_default,
        "blocking": blocks_writes(mode),
        "state_file": str(state_path()),
    }
