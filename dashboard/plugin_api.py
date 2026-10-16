"""readonly-guard backend, mounted at /api/plugins/readonly-guard/.

Loaded by the gateway/web server with ``spec_from_file_location`` (NOT as a
package), so the plugin's own ``state.py`` is reached by putting the plugin
directory on sys.path — one source of truth for the switch, shared with the
agent half and the ``/readonly`` slash command.

Routes:
  GET  /state          -> {"enabled": bool, "state_file": str}
  POST /toggle         -> flips the switch, returns the new state
  POST /state {enabled: bool} -> sets the switch explicitly

The ``enabled`` shape is 1.x's: the mode API (and this file's mode-shaped
rewrite) lands with the desktop half, so the running chip keeps working in
between.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from state import MODE_READONLY, MODE_WRITABLE, blocks_writes, set_mode, state_path  # noqa: E402

router = APIRouter()


def _payload() -> dict:
    return {"enabled": blocks_writes(), "state_file": str(state_path())}


@router.get("/state")
async def get_state():
    return _payload()


@router.post("/toggle")
async def toggle():
    set_mode(MODE_WRITABLE if blocks_writes() else MODE_READONLY, source="dashboard")
    return _payload()


@router.post("/state")
async def post_state(body: dict | None = None):
    body = body or {}
    if "enabled" not in body:
        return {"error": "body must be {\"enabled\": true|false}"}
    set_mode(MODE_READONLY if body["enabled"] else MODE_WRITABLE, source="dashboard")
    return _payload()
