"""readonly-guard backend, mounted at /api/plugins/readonly-guard/.

Loaded by the gateway/web server with ``spec_from_file_location`` (NOT as a
package), so the plugin's own ``state.py`` is reached by putting the plugin
directory on sys.path — one source of truth for the mode, shared with the agent
half and the ``/readonly`` slash command.

Routes:
  GET  /state        -> {"mode": str, "blocking": bool, "modes": [str], "state_file": str}
  POST /state {mode} -> sets the mode, returns the new state
  POST /toggle       -> advances to the next mode, returns the new state

A rejected request answers 200 with ``{"error": ...}`` and writes nothing. A body
that is not a JSON object never reaches the handler: the ``dict | None`` annotation
is validated first, so FastAPI answers 422 with ``{"detail": ...}`` instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from state import MODES, next_mode, set_mode, status  # noqa: E402

router = APIRouter()


def _payload() -> dict:
    """The mode payload every route returns, straight from the state module.

    ``state.status()`` is the one place that shape is defined — the routes must not
    re-spell it, or the two drift the first time a field is added.
    """
    return status()


@router.get("/state")
async def get_state():
    return _payload()


@router.post("/toggle")
async def toggle():
    set_mode(next_mode(), source="dashboard")
    return _payload()


@router.post("/state")
async def post_state(body: dict | None = None):
    body = body or {}
    mode = body.get("mode")
    if mode not in MODES:
        return {"error": 'body must be {"mode": "readonly"|"plan"|"writable"}'}
    set_mode(mode, source="dashboard")
    return _payload()
