"""readonly-guard backend, mounted at /api/plugins/readonly-guard/.

Loaded by the gateway/web server with ``spec_from_file_location`` (NOT as a package),
so the plugin's own modules are reached by putting the plugin directory on sys.path —
one source of truth for the mode, shared with the agent half and ``/readonly``.

Routes:
  GET  /state?session=<id>      -> that session's resolved state
  POST /state {mode, session}   -> set that session's mode
  POST /state {mode}            -> set the DEFAULT for new sessions (the setting)
  POST /toggle {session?}       -> advance the session's mode, or the default

A request with no ``session`` is not "the current session" — the dashboard has no way to
know one — it is the default that NEW sessions start with. That is exactly the control
the desktop chip needs while a chat has no session id yet.

A rejected request answers 200 with ``{"error": ...}`` and writes nothing. A body that is
not a JSON object never reaches the handler: the ``dict | None`` annotation is validated
first, so FastAPI answers 422 with ``{"detail": ...}`` instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Query

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from settings import default_mode  # noqa: E402
from state import MODES, next_mode, set_session_mode, status  # noqa: E402

router = APIRouter()

#: Registry id, and therefore the key under ``plugins.entries.<id>.settings``.
PLUGIN_ID = "readonly-guard"


def _payload(session: str = "") -> dict:
    """The one payload shape — ``state.status`` defines it, the routes do not re-spell it."""
    return status(str(session or ""), default=default_mode())


def _write_setting(values: dict) -> None:
    """Hand values to Hermes' own writer.

    It validates against ``plugin.yaml``'s ``config_schema`` and shares the lock and
    atomicity the CLI and the Plugins tab use. Imported lazily (and through this seam)
    because it pulls in Hermes' whole config stack, which a bare test interpreter does
    not have.
    """
    from hermes_cli.plugins_settings import save_plugin_settings
    save_plugin_settings(PLUGIN_ID, _PLUGIN_DIR, values)


def _save_default(mode: str) -> str:
    """Write the plugin setting. Returns ``""`` on success, else the reason it failed.

    ``ValueError`` on schema drift, ``PermissionError`` on a managed install.
    """
    try:
        _write_setting({"default_mode": mode})
    except Exception as exc:  # noqa: BLE001 - the reason is returned, not raised
        return f"{type(exc).__name__}: {exc}"
    return ""


def _apply(mode: str, session: str) -> dict:
    """Write one mode to the session, or to the setting when there is no session."""
    if session:
        set_session_mode(session, mode, source="dashboard")
        return _payload(session)
    problem = _save_default(mode)
    if problem:
        return {"error": f"cannot set the default for new sessions: {problem}"}
    # Echo what was written. This process may hold no config reader (the dashboard can
    # be mounted without a plugin context), and the caller needs the outcome, not a
    # default read from a stale reader.
    return status("", default=mode)


@router.get("/state")
async def get_state(session: str = Query("", alias="session")):
    return _payload(session)


@router.post("/state")
async def post_state(body: dict | None = None):
    body = body or {}
    mode = body.get("mode")
    if mode not in MODES:
        return {"error": 'body must be {"mode": "readonly"|"plan"|"writable", "session": "<id>" (optional)}'}
    return _apply(mode, str(body.get("session") or ""))


@router.post("/toggle")
async def toggle(body: dict | None = None):
    session = str((body or {}).get("session") or "")
    current = status(session, default=default_mode())["mode"]
    return _apply(next_mode(current), session)
