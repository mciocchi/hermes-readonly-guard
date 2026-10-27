"""readonly-guard — code-enforced posture with a runtime mode switch.

Three modes, defined in ``state.py``: ``readonly``, ``plan``, ``writable``.

Two contributions:

1. ``pre_tool_call`` hook: blocks every tool call that is not on the inspection
   allowlist whenever the mode restricts (``readonly`` or ``plan``). Plan mode also
   admits single read-only shell commands through ``terminal`` (``probe.py``).
   A directive/control hook, so the ``block`` return short-circuits the tool
   before the approval layer — ``--yolo`` and ``approvals.mode: off`` cannot
   lift it. A callback that raises or times out fails CLOSED.
2. ``/readonly`` slash command: ``/readonly [status|readonly|plan|writable|on|off|toggle]``
   flips the switch in CLI, TUI, desktop, and gateway sessions. The desktop
   chip does the same thing over ``dashboard/plugin_api.py``.

The switch is deliberately NOT exposed as an agent tool: an agent that can turn
off its own guard has no guard.
"""

from __future__ import annotations

from pathlib import Path

from .state import (
    MODE_PLAN,
    MODE_READONLY,
    MODE_WRITABLE,
    MODES,
    blocks_writes,
    next_mode,
    read_mode,
    set_mode,
    state_path,
)

from .probe import PROBE_PROGRAMS, probe_refusal

try:  # Hermes' own /plan prompt. Absent only in an interpreter without the repo on sys.path.
    from agent.plan_prompt import build_plan_prompt
except Exception:  # pragma: no cover - the fallback path is exercised when PYTHONPATH is unset
    build_plan_prompt = None

#: Injected when ``agent.plan_prompt`` is unavailable. Deliberately short: the
#: procedure lives in the ``plan`` skill, so duplicating its text here would drift.
_PLAN_FALLBACK_CONTEXT = (
    "PLAN MODE (readonly-guard): this session is in plan mode — plan, do not execute. "
    "Load the procedure with skill_view(name='plan') and follow it."
)

#: Appended to Hermes' plan prompt so the skill is the authoring reference.
_PLAN_SKILL_POINTER = (
    "The full planning procedure is available as the `plan` skill: "
    "run skill_view(name='plan') and follow it."
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

#: Path components a plan file must sit under. Components, not a substring test,
#: so ``notes/.hermes/plans/x.md`` still counts as the plans directory.
PLAN_DIR_PARTS = (".hermes", "plans")
PLAN_SUFFIX = ".md"

_READONLY_MESSAGE = (
    "BLOCKED: this Hermes instance is in read-only mode (readonly-guard). "
    "Only inspection tools are available: {allowed}. "
    "Nothing may be written, executed, sent, or scheduled. Do not retry or "
    "rephrase — report what you found in the conversation instead. "
    "The user can leave read-only mode with /readonly writable."
).format(allowed=", ".join(sorted(READ_ONLY_TOOLS)))

_PLAN_MESSAGE = (
    "BLOCKED: this Hermes instance is in PLAN mode (readonly-guard). "
    "Inspection tools are available ({allowed}), plus write_file and a single-file "
    "patch for the plan markdown under .hermes/plans/, plus probe commands through "
    "terminal "
    "({probes}). Do not execute, edit, or send anything — produce the plan "
    "instead. The user can leave plan mode with /readonly writable."
).format(
    allowed=", ".join(sorted(READ_ONLY_TOOLS)),
    probes=", ".join(sorted(PROBE_PROGRAMS)),
)

_USAGE = "usage: /readonly [status|readonly|plan|writable|on|off|toggle]"

#: Shorthand for the modes people already typed in 1.x.
_ALIASES = {"on": MODE_READONLY, "off": MODE_WRITABLE}

_MODE_BLURB = {
    MODE_READONLY: "ON (read-only) — every non-inspection tool call is blocked.",
    MODE_PLAN: "PLAN — inspection tools and the plan markdown only; every turn is planned, not executed.",
    MODE_WRITABLE: "OFF (writes allowed) — nothing is blocked.",
}


def _plans_root(parts: tuple[str, ...]) -> Path | None:
    """The path prefix up to and including a ``.hermes``/``plans`` pair, or None if there is none."""
    for i in range(len(parts) - 1):
        if parts[i : i + 2] == PLAN_DIR_PARTS:
            return Path(*parts[: i + 2])
    return None


def _is_plan_file(args: object) -> bool:
    """True when a write_file target is a markdown plan that lands in a ``.hermes/plans/`` directory.

    The verdict is made on resolved paths, because a component test on the raw string
    accepts ``.hermes/plans/../../../evil.md`` — which names a plans directory and then
    leaves it. The rule is containment: the raw path must name a ``.hermes``/``plans``
    directory, and the file it resolves to must sit inside the directory that name
    resolves to. A symlinked ``.hermes`` or ``.hermes/plans`` therefore still works (the
    name refers to whatever the user pointed it at), while a symlink *inside* plans, a
    symlinked leaf, and anything that climbs out are all refused. A path that cannot be
    expanded or resolved (``~unknown-user/...`` raises) is not a plan file either.
    """
    if not isinstance(args, dict):
        return False
    path = args.get("path")
    if not isinstance(path, str) or not path.strip():
        return False
    raw_path = path.strip()
    if Path(raw_path).suffix != PLAN_SUFFIX:
        return False
    root = _plans_root(Path(raw_path).parts)
    if root is None:
        return False
    try:
        return Path(raw_path).expanduser().resolve().is_relative_to(root.expanduser().resolve())
    except (OSError, ValueError, RuntimeError):
        return False


#: Tools that may touch a plan markdown in plan mode. `patch` belongs here because
#: superseding an existing plan is an edit, not a new file — and `write_file` over a
#: file the task has not read is refused by the tool, which turns "supersede" into a
#: read-then-rewrite.
_PLAN_EDIT_TOOLS = frozenset({"write_file", "patch"})


def _is_plan_edit(tool_name: str, args: object) -> bool:
    """True when the call writes or patches one plan markdown, and nothing else.

    `patch` has two shapes and only one is bounded: ``mode="replace"`` (the default)
    edits the file named in ``path``, while ``mode="patch"`` is V4A and may carry
    several file headers — including a decoy ``path`` naming a plan file. The handler
    accepts V4A from any model, so the ``mode`` check is what keeps a plan-mode edit
    from reaching ``src/app.py``.
    """
    if tool_name not in _PLAN_EDIT_TOOLS or not isinstance(args, dict):
        return False
    if tool_name == "patch" and args.get("mode", "replace") != "replace":
        return False
    return _is_plan_file(args)


def guard(tool_name, args=None, task_id="", **kwargs):
    """pre_tool_call directive: block anything the current mode does not allow."""
    mode = read_mode()
    if not blocks_writes(mode):
        return None
    if tool_name in READ_ONLY_TOOLS:
        return None
    if mode == MODE_PLAN and _is_plan_edit(tool_name, args):
        return None
    if mode == MODE_PLAN and tool_name == "terminal":
        refusal = probe_refusal(args)
        if refusal is None:
            return None
        return {"action": "block", "message": f"{_PLAN_MESSAGE} Refused: {refusal}."}
    return {"action": "block", "message": _PLAN_MESSAGE if mode == MODE_PLAN else _READONLY_MESSAGE}


def _plan_context(user_message=None) -> str:
    """The plan-mode prompt for this turn, plus the pointer to the `plan` skill.

    Reusing ``build_plan_prompt`` is deliberate: the plugin must not maintain a
    second copy of Hermes' planning contract, and ``/plan`` must not drift from
    what plan mode injects.
    """
    task = user_message if isinstance(user_message, str) else ""
    if build_plan_prompt is None:
        return _PLAN_FALLBACK_CONTEXT
    try:
        return build_plan_prompt(task) + "\n\n" + _PLAN_SKILL_POINTER
    except Exception:
        return _PLAN_FALLBACK_CONTEXT


def plan_directive(user_message=None, **kwargs):
    """pre_llm_call directive: in plan mode, hand this turn to the plan skill."""
    if read_mode() != MODE_PLAN:
        return None
    return {"context": _plan_context(user_message)}


def _handle_readonly(raw_args: str) -> str:
    """/readonly [status|readonly|plan|writable|on|off|toggle] — raw_args is everything after the name."""
    arg = (raw_args or "").strip().lower()
    if arg in ("", "status"):
        mode = read_mode()
        return (
            f"readonly-guard: {mode} — {_MODE_BLURB[mode]}\n"
            f"modes: {', '.join(MODES)}\n"
            f"state file: {state_path()}\n"
            f"{_USAGE}\n"
            "The switch applies to the NEXT tool call — no restart."
        )
    if arg == "toggle":
        mode = next_mode()
    elif arg in _ALIASES:
        mode = _ALIASES[arg]
    elif arg in MODES:
        mode = arg
    else:
        return f"readonly-guard: unknown argument {arg!r} — {_USAGE}"
    set_mode(mode, source="slash_command")
    return f"readonly-guard: {mode} — {_MODE_BLURB[mode]}"


def register(ctx):
    ctx.register_hook("pre_tool_call", guard)
    ctx.register_hook("pre_llm_call", plan_directive)
    ctx.register_command(
        "readonly",
        handler=_handle_readonly,
        description="Show or set the readonly-guard mode (readonly/plan/writable)",
        args_hint="[status|readonly|plan|writable|on|off|toggle]",
    )
