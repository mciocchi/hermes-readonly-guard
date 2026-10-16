"""readonly-guard backend, mounted at /api/plugins/readonly-guard/.

Loaded by the gateway/web server with ``spec_from_file_location`` (NOT as a
package), so the plugin's own ``state.py`` is reached by putting the plugin
directory on sys.path — one source of truth for the switch, shared with the
agent half and the ``/readonly`` slash command.

Routes:
  GET  /state          -> {"enabled": bool, "state_file": str}
  POST /toggle         -> flips the switch, returns the new state
  POST /state {enabled: bool} -> sets the switch explicitly
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from state import read_only_enabled, set_read_only, state_path  # noqa: E402

router = APIRouter()


def _payload() -> dict:
    return {"enabled": read_only_enabled(), "state_file": str(state_path())}


@router.get("/state")
async def get_state():
    return _payload()


@router.post("/toggle")
async def toggle():
    set_read_only(not read_only_enabled(), source="dashboard")
    return _payload()


@router.post("/state")
async def post_state(body: dict | None = None):
    body = body or {}
    if "enabled" not in body:
        return {"error": "body must be {\"enabled\": true|false}"}
    set_read_only(bool(body["enabled"]), source="dashboard")
    return _payload()
