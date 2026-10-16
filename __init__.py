"""readonly-guard — code-enforced read-only posture with a runtime switch.

Two contributions:

1. ``pre_tool_call`` hook: blocks every tool call that is not on the read-only
   allowlist. A directive/control hook, so the ``block`` return short-circuits
   the tool before the approval layer — ``--yolo`` and ``approvals.mode: off``
   cannot lift it. A callback that raises or times out fails CLOSED.
2. ``/readonly`` slash command: ``/readonly [status|on|off|toggle]`` flips the
   switch in CLI, TUI, desktop, and gateway sessions. The desktop chip does the
   same thing over ``dashboard/plugin_api.py``.

The switch is deliberately NOT exposed as an agent tool: an agent that can turn
off its own guard has no guard.
"""

from __future__ import annotations

from .state import (
    MODE_READONLY,
    MODE_WRITABLE,
    blocks_writes,
    next_mode,
    read_mode,
    set_mode,
    state_path,
)

READ_ONLY_TOOLS = {
    # filesystem reads
    "read_file",
    "search_files",
    # web / media inspection
    "web_search",
    "web_extract",
    "vision_analyze",
    "video_analyze",
    # history
    "session_search",
    # skills: list/view only — skill_manage is a write
    "skills_list",
    "skill_view",
    # planning / conversation
    "todo_list",
    "clarify",
    # desktop read-only affordances
    "read_terminal",
    "read_window_below",
}

MESSAGE = (
    "BLOCKED: this Hermes instance is in read-only mode (readonly-guard). "
    "Only inspection tools are available: {allowed}. "
    "Nothing may be written, executed, sent, or scheduled. Do not retry or "
    "rephrase — report what you found in the conversation instead. "
    "The user can re-enable writes with /readonly off."
).format(allowed=", ".join(sorted(READ_ONLY_TOOLS)))


def guard(tool_name, args=None, task_id="", **kwargs):
    """pre_tool_call directive: block anything that is not a read-only tool."""
    if not blocks_writes():
        return None
    if tool_name in READ_ONLY_TOOLS:
        return None
    return {"action": "block", "message": MESSAGE}


def _handle_readonly(raw_args: str) -> str:
    """/readonly [status|on|off|toggle] — raw_args is everything after the name."""
    arg = (raw_args or "").strip().lower()
    if arg in ("", "status"):
        mode = read_mode()
        return (
            f"readonly-guard: {mode} (blocking={'yes' if blocks_writes(mode) else 'no'})\n"
            f"state file: {state_path()}\n"
            "usage: /readonly [status|on|off|toggle]\n"
            "The switch applies to the NEXT tool call — no restart."
        )
    if arg == "on":
        set_mode(MODE_READONLY, source="slash_command")
        return "readonly-guard: ON — every non-read-only tool call is now blocked."
    if arg == "off":
        set_mode(MODE_WRITABLE, source="slash_command")
        return "readonly-guard: OFF — writes and shell are allowed again."
    if arg == "toggle":
        new = next_mode()
        set_mode(new, source="slash_command")
        return f"readonly-guard: {'ON (read-only)' if new == MODE_READONLY else 'OFF (writes allowed)'}."
    return f"readonly-guard: unknown argument {arg!r} — usage: /readonly [status|on|off|toggle]"


def register(ctx):
    ctx.register_hook("pre_tool_call", guard)
    ctx.register_command(
        "readonly",
        handler=_handle_readonly,
        description="Show or flip the read-only guard (on/off/toggle)",
        args_hint="[status|on|off|toggle]",
    )
