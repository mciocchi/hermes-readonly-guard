# readonly-guard

A Hermes plugin that enforces a posture **in code**, not in the prompt: while a
restricting mode is active, every tool call that is not on a small inspection
allowlist is blocked before it runs.

## Modes

One mode **per session**, stored in `<HERMES_HOME>/readonly-guard.state`. Flipping the
guard in one chat cannot loosen another chat that is already running — that is the point
of the plugin. A session that has never been switched follows the `default_mode` setting,
which defaults to `readonly`.

| Mode (per session) | Inspection tools | `write_file` / `patch` to `.hermes/plans/*.md` | Probe commands via `terminal` | Everything else | Extra behaviour |
|---|---|---|---|---|---|
| `readonly` | allowed | blocked | blocked | blocked | — |
| `plan` | allowed | allowed (single-file replace mode) | allowed (allowlist, see below) | blocked | every turn is handed Hermes' plan prompt plus a pointer to the `plan` skill |
| `writable` | allowed | allowed | allowed | allowed | — |

A missing, unreadable, unparseable, or non-object state file holds **no sessions**, so
every session reads the configured default — and that default is the restrictive one
(`readonly`). A 2.x file's top-level `mode` is ignored: it described the machine, and
nothing may inherit a looser posture from it.

| Surface | What it switches |
|---|---|
| `/readonly [status\|readonly\|plan\|writable\|on\|off\|toggle]` | the session you type it in |
| Desktop status-bar control / palette rows | the focused chat; on a fresh draft, the default for new sessions |
| `POST /api/plugins/readonly-guard/state {"mode": …, "session": "<id>"}` | that session (no `session` → the default) |
| `plugins.entries.readonly-guard.settings.default_mode` | what a NEW session starts as |

## The default mode setting

`default_mode` decides what a session starts as. Set it in Settings → Plugins (the form
comes from `plugin.yaml`'s `config_schema`), by clicking the status-bar control while no
chat has a session yet, or by editing `config.yaml`:

```yaml
plugins:
  entries:
    readonly-guard:
      settings:
        default_mode: readonly   # readonly | plan | writable
```

Changing it never touches a session that already has its own mode. An unrecognised value
reads as `readonly`.

## Design concerns

- **One state file, every surface, one entry per session.** The agent hooks, the
  `/readonly` command and the dashboard API all read and write the same file, so they
  cannot disagree — and each session has its own entry, so a flip in one cannot loosen
  another. `session_id` is the agent's durable id; `task_id` is a fresh uuid per turn and
  is deliberately unused.
- **A subagent inherits the session that spawned it.** A delegated child has its own
  `session_id`, but the process still names its parent, so the child runs under the
  parent's mode. Without that, delegated work would silently run read-only under a
  writable chat.
- **The table is written under a lock.** Two writers in one process (the chip and
  `/readonly`) each read the table and write it back; without the lock one of them loses
  the other's session. Readers are safe regardless: writes are atomic (`mkstemp` +
  `replace`).
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
- **The plan-file exception is narrow.** Plan mode permits `write_file`, and `patch` in
  its single-file `replace` mode, only for a `.md` path that names a `.hermes/plans`
  directory *and* resolves inside it, so `.hermes/plans/../../../evil.md`, a symlink
  inside `plans`, and a symlinked leaf are all refused. A symlinked `.hermes` or
  `.hermes/plans` still works: the name refers to the directory the user pointed it at.
  Patching is what lets a session supersede an existing plan instead of rewriting it.
- **V4A patches are refused in plan mode, even for a plan file.** `patch`'s `mode="patch"`
  shape can carry several file headers (and a decoy `path`), so the carve-out keys on
  `mode="replace"` only; a model that emits V4A has to use replace mode or `write_file`.
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
├── state.py                the session table: get_session_mode / set_session_mode /
│                           next_mode / blocks_writes / status — the source of truth
├── settings.py             the one setting: default_mode (read via ctx.get_config)
├── dashboard/
│   ├── manifest.json       capability-page metadata
│   └── plugin_api.py       FastAPI router at /api/plugins/readonly-guard/
├── desktop/
│   └── plugin.js           status-bar mode control + palette commands (ESM)
├── tests/                  stdlib unittest, one file per concern
└── plugin.yaml             manifest: provides_hooks, config_schema (default_mode)
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

## Upgrading from 2.x

2.x stored ONE mode for the whole machine in `readonly-guard.state`. 3.0 ignores that
value: a machine-wide posture is what this release removes, and inheriting it would hand a
looser mode to every session at once. Every session therefore starts at `default_mode`
(`readonly` unless you changed it). The file is replaced the first time a session is
switched, and the old value is never read.

The desktop half changed shape (a per-session chip), so press **Rescan** in
Capabilities → Plugins after upgrading.
