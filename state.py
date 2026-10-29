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

try:  # Hermes' authoritative home: %LOCALAPPDATA% on Windows, profiles, session overrides
    from hermes_constants import get_hermes_home as _hermes_home_resolver
except Exception:  # standalone import (the dashboard half) or no Hermes on sys.path
    _hermes_home_resolver = None

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


def _hermes_home() -> str:
    """Hermes' home directory, or the best available guess when it cannot be asked.

    The state file has to live where Hermes is actually running, which is not always
    ``~/.hermes``: Windows uses ``%LOCALAPPDATA%/hermes``, a profile moves it, and a
    session can carry its own override. Asking the resolver is the only way to follow all
    three; the fallback keeps a bare interpreter (a dashboard half imported without
    Hermes, a unit test) working.
    """
    if _hermes_home_resolver is not None:
        try:
            return str(_hermes_home_resolver())
        except Exception:
            pass
    return os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")


def state_path() -> Path:
    return Path(_hermes_home()) / STATE_FILENAME


def _read_raw() -> dict:
    """The state file as a mapping; anything else reads as empty.

    Missing, unreadable, unparseable, and parseable-but-not-an-object all collapse to
    ``{}`` so every one of them means "no sessions" rather than raising into the hook
    (which would block every tool call behind a confusing error) or into the dashboard
    (which would 500).
    """
    try:
        raw = json.loads(state_path().read_text(encoding="utf-8"))
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


def session_entry(session_id: str) -> dict | None:
    """The raw entry for one session, or ``None`` when it follows the default."""
    return _sessions().get(str(session_id)) if session_id else None


#: Extra keys a writable entry carries: when its clock last started, and the turn that
#: started it. Both absent on a 3.5 entry, which is why a missing stamp means "not yet".
RENEWED_AT = "renewed_at"
RENEWED_TURN = "renewed_turn"


def effective_mode(
    entry: dict | None, *, ttl_minutes: int, now: float | None = None, turn_id: str = ""
) -> str | None:
    """The mode an entry really grants now, applying the writable expiry.

    Four ways a grant survives: it is not writable, the TTL is off, the clock never
    started (a 3.5 entry), or this is the turn that renewed it — so a turn that is already
    running is never cut off mid-way, which is the whole point of measuring silence rather
    than workload.
    """
    if not isinstance(entry, dict):
        return None
    mode = entry.get("mode")
    if mode not in MODES:
        return None
    if mode != MODE_WRITABLE or ttl_minutes <= 0:
        return mode
    if turn_id and str(entry.get(RENEWED_TURN) or "") == str(turn_id):
        return mode
    renewed = entry.get(RENEWED_AT)
    if not isinstance(renewed, (int, float)):
        return mode
    if (now if now is not None else time.time()) - float(renewed) > ttl_minutes * 60:
        return MODE_READONLY
    return mode


def expires_in(
    entry: dict | None, *, ttl_minutes: int, now: float | None = None
) -> int | None:
    """Seconds left on a writable grant, or ``None`` when nothing is counting down."""
    if not isinstance(entry, dict) or entry.get("mode") != MODE_WRITABLE or ttl_minutes <= 0:
        return None
    renewed = entry.get(RENEWED_AT)
    if not isinstance(renewed, (int, float)):
        return None
    left = ttl_minutes * 60 - ((now if now is not None else time.time()) - float(renewed))
    return max(0, int(left))


def renew_or_lapse(
    session_id: str, turn_id: str, ttl_minutes: int, now: float | None = None
) -> str:
    """Turn-start housekeeping for one session: renew the clock, or latch it to readonly.

    Only a ``writable`` entry is touched, so a readonly or plan session costs no write.
    Latching is a real write on purpose: an expired grant must not come back to life
    because the user said something after the deadline.
    """
    if not session_id or ttl_minutes <= 0:
        return get_session_mode(session_id) or ""
    stamp = now if now is not None else time.time()
    with _WRITE_LOCK:
        table = dict(_sessions())
        entry = table.get(str(session_id))
        if not entry or entry.get("mode") != MODE_WRITABLE:
            return str((entry or {}).get("mode") or "")
        if effective_mode(entry, ttl_minutes=ttl_minutes, now=stamp) == MODE_READONLY:
            table[str(session_id)] = {
                "mode": MODE_READONLY, "updated_at": stamp, "updated_by": "expiry",
            }
            _write({"version": SCHEMA_VERSION, "sessions": table})
            return MODE_READONLY
        entry = dict(entry)
        entry[RENEWED_AT] = stamp
        entry[RENEWED_TURN] = str(turn_id)
        table[str(session_id)] = entry
        _write({"version": SCHEMA_VERSION, "sessions": table})
    return MODE_WRITABLE


def get_session_mode(session_id: str) -> str | None:
    """This session's explicit mode, or ``None`` when it follows the default."""
    if not session_id:
        return None
    entry = _sessions().get(str(session_id))
    return str(entry["mode"]) if entry else None


#: `os.replace` refusals to tolerate before giving up. Windows returns PermissionError
#: while another process has the destination open; the window is a dashboard poll, so five
#: attempts over ~300ms covers it without stalling a tool call.
_REPLACE_ATTEMPTS = 5
_REPLACE_DELAY = 0.02


def _replace_with_retry(src: str, dst: Path) -> None:
    """``os.replace`` with a short retry, because Windows refuses to replace an open file.

    POSIX renames an open path happily. Windows does not, and CPython opens files without
    FILE_SHARE_DELETE, so a concurrent reader — the desktop chip's ``GET /state`` — makes
    the replace fail for the few milliseconds it holds the file. The last error is raised
    once the attempts run out: a write that did not happen must not look like one that did.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_DELAY * (attempt + 1))


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
        with os.fdopen(handle, "w", encoding="utf-8") as tmp:
            tmp.write(json.dumps(payload, indent=2) + "\n")
        _replace_with_retry(tmp_name, path)
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
        entry = {"mode": mode, "updated_at": now, "updated_by": source}
        if mode == MODE_WRITABLE:          # start the expiry clock when arming
            entry[RENEWED_AT] = now
            entry[RENEWED_TURN] = ""
        table[str(session_id)] = entry
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


def status(session_id: str = "", default: str = DEFAULT_MODE, ttl_minutes: int = 0) -> dict:
    """The payload every surface reads: this session's mode, and what it means.

    ``source`` is ``"session"`` when the session has its own entry and ``"default"``
    when it is following the setting — the desktop chip labels the two differently.
    ``ttl_minutes`` is passed by the caller (this module does not read settings), so an
    expired grant reads as ``readonly`` here exactly as the guard decides it.
    """
    effective_default = default if default in MODES else DEFAULT_MODE
    entry = session_entry(session_id)
    mode = (effective_mode(entry, ttl_minutes=ttl_minutes) if entry else None) or effective_default
    return {
        "modes": list(MODES),
        "session": str(session_id),
        "mode": mode,
        "source": "session" if entry else "default",
        "default": effective_default,
        "blocking": blocks_writes(mode),
        "expires_in": expires_in(entry, ttl_minutes=ttl_minutes) if mode == MODE_WRITABLE else None,
        "expiry_minutes": int(ttl_minutes),
        "state_file": str(state_path()),
    }
