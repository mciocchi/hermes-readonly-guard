# readonly-guard

A Hermes plugin that enforces a posture **in code**, not in the prompt: while a
restricting mode is active, every tool call that is not on a small inspection
allowlist is blocked before it runs.

## Modes

One mode at a time, stored in `<HERMES_HOME>/readonly-guard.state`:

| Mode | Inspection tools | `write_file` to `.hermes/plans/*.md` | Probe commands via `terminal` | Everything else | Extra behaviour |
|---|---|---|---|---|---|
| `readonly` | allowed | blocked | blocked | blocked | — |
| `plan` | allowed | allowed | allowed (allowlist, see below) | blocked | every turn is handed Hermes' plan prompt plus a pointer to the `plan` skill |
| `writable` | allowed | allowed | allowed | allowed | — |

A missing, unreadable, unparseable, or non-object state file reads as `readonly`:
the plugin exists to restrict, so the surprising default is the restrictive one.
A 1.x file that stored only `enabled` is migrated on read, and writes keep that key
so an older reader never sees a file it cannot understand.

Flip it with `/readonly [status|readonly|plan|writable|on|off|toggle]` (the `on`/`off`
aliases are 1.x's), with the desktop status-bar control, or over
`POST /api/plugins/readonly-guard/state {"mode": ...}`.

## Design concerns

- **One state file, every surface.** The agent hooks, the `/readonly` command and the
  dashboard API all read and write the same file, so they cannot disagree. The mode is
  machine-wide (one file per `HERMES_HOME`), not per session.
- **Fail closed.** `pre_tool_call` is a policy hook: a callback that raises or times
  out blocks the tool instead of allowing it, and every unrecognised state reads as the
  restrictive mode.
- **Fail closed without surprising the reader.** A path that cannot be expanded or
  resolved is a block, not an exception — a raising hook blocks the tool, but with a
  policy-error message instead of the guard's own.
- **No self-service.** The switch is not an agent tool. An agent that can turn off its
  own guard has no guard.
- **No duplicated planning prompt.** Plan mode injects
  `agent.plan_prompt.build_plan_prompt` — the same builder `/plan` uses — then points at
  the `plan` skill for the authoring procedure. If that import is unavailable the plugin
  injects a short pointer to the skill instead of a copy of the prompt, so the two can
  never drift.
- **The plan-file exception is narrow.** Plan mode permits `write_file` only for a `.md`
  path that names a `.hermes/plans` directory *and* resolves inside it, so
  `.hermes/plans/../../../evil.md`, a symlink inside `plans`, and a symlinked leaf are
  all refused. A symlinked `.hermes` or `.hermes/plans` still works: the name refers to
  the directory the user pointed it at.
- **Plan mode may run probe commands, and only single ones.** `probe.py` admits one
  program per call, chosen from a fixed table, with no shell composition at all: `;`,
  `&&`, `|`, `>`, `<`, `$(…)`, backticks and newlines are refused outright rather than
  parsed. `git` is limited to read-only sub-commands (`status`, `log`, `diff`, `show`,
  `grep`, `rev-parse`, …) with `-c`/`--exec-path`/`--paginate` and output/pager flags
  refused; `find` is limited to an allowlist of primaries (`-exec`, `-delete` and
  `-fprint` are not on it). **This is a speed bump, not a sandbox** — every verdict is a
  string decision about a command a shell will then interpret, so anything unrecognised
  is refused and a useful command sometimes is too. `readonly` mode keeps `terminal`
  blocked entirely: it is the mode you leave on when nothing may run.
- **`patch` is never permitted, even for a plan file.** The exception is scoped to
  `write_file`: it exists so a plan can be delivered, not so files can be edited.
- **`todo_list` is allowlisted on purpose.** It writes per-session task state, not files
  or remote state, and a plan is built with one.
- **Contributions name their area with the SDK's constants, never a literal.** `'PALETTE_AREA'`
  is not the palette — the constant's value is `'palette'` — and a literal registers
  silently and never renders. `tests/test_desktop_contract.py` fails on any literal area
  id; that check exists because 1.1 shipped three dead palette rows exactly this way.

## Project structure

```
readonly-guard/
├── __init__.py             agent half: pre_tool_call guard, pre_llm_call plan
│                           directive, /readonly command, register(ctx)
├── state.py                the mode file: read_mode / set_mode / next_mode /
│                           blocks_writes / status — the single source of truth
├── dashboard/
│   ├── manifest.json       capability-page metadata
│   └── plugin_api.py       FastAPI router at /api/plugins/readonly-guard/
├── desktop/
│   └── plugin.js           status-bar mode control + palette commands (ESM)
├── tests/                  stdlib unittest, one file per concern
└── plugin.yaml             manifest: provides_hooks: pre_tool_call, pre_llm_call
```

## Running the tests

The tests are stdlib `unittest` (there is no pytest in the Hermes venv). Use the Hermes
venv — the dashboard tests import `fastapi` and `httpx`:

```bash
# from the plugin directory
$HERMES_REPO/venv/bin/python -m unittest discover -s tests -t tests -v
```

No test is skipped. One of them (`test_the_injection_reuses_the_built_in_plan_prompt…`)
needs `agent.plan_prompt`, which this venv can import because Hermes is installed
editable; the fallback path that covers the other case patches the name instead, so
both branches are exercised either way.

Desktop half (a plain ESM file, so it must be checked as one):

```bash
cp desktop/plugin.js /tmp/plugin.mjs && node --check /tmp/plugin.mjs
```

## Environment variables

This plugin defines **no** environment variables of its own. It reads one variable owned
by Hermes core:

| Variable | Meaning |
|---|---|
| `HERMES_HOME` | Hermes profile directory; the mode file is `<HERMES_HOME>/readonly-guard.state`. Falls back to `~/.hermes`. |

## Installing a changed desktop half

The Desktop app loads **its own copy** of `desktop/plugin.js` from
`<HERMES_HOME>/desktop-plugins/readonly-guard/`, refreshing it only when the package copy
is newer. After editing `desktop/plugin.js`, sidebar → Capabilities → Plugins → **Rescan**
(or restart the app), then confirm:

```bash
hermes plugins doctor readonly-guard    # no "stale copy" warning once refreshed
```
