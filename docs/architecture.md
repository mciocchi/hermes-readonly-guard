---
schema: architecture/1
version: 1
status: draft
project: hermes-readonly-guard
---

# hermes-readonly-guard

## 1. Problem

A Hermes agent runs with the user's own privileges, and the approval layer is advisory: `--yolo`
and `approvals.mode: off` both lift it, and a prompt-level instruction to "not write" is only a
request the model may ignore after a compaction. A user who wants an agent to look at a repo
without touching it has no mechanism that survives either. This plugin holds a session to a
posture in code: the refusal happens in `pre_tool_call`, ahead of the approval layer, one session
at a time, and the switch is not a tool the agent can call.

## 2. Components

| Component | Responsibility | Owns state | Inputs | Outputs | Delivered by |
|---|---|---|---|---|---|
| Guard hook (`guard()`) | Decides allow or deny for every tool call in a restricting mode | No — reads the mode store | tool name and args, session id | allow, or a denial message naming the mode | 01 |
| Probe filter (`probe.py`) | Admits one allowlisted read-only command per call, or refuses it | No — a frozen 29-name program table plus per-flag denials | command string | allow, or the reason it is not a probe | 01 |
| Mode store (`state.py`) | Per-session mode table and the writable lease clock | Yes — `<HERMES_HOME>/readonly-guard.state` | mode writes, turn boundaries | effective mode per session | 01 |
| Settings reader (`settings.py`) | `default_mode` and `writable_expiry_minutes`, fail-closed | No — reads the plugin settings JSON | manifest `config_schema` keys | values, with defaults when absent or malformed | 01 |
| Plan directive (`plan_directive()`) | Hands the agent Hermes' own plan prompt on every turn of a plan-mode session | No | turn context | injected prompt text | 01 |
| Desktop control (`desktop/plugin.js`) | Status-bar segmented control with the lease countdown, and the palette rows | No | mode payload | `POST /state` | 01 |
| Keybind contributions (`desktop/plugin.js`) | Registers the three keybind actions in `KEYBINDS_AREA` — `mod+alt+r`, `mod+alt+p`, `writable` unbound — and refuses when no session is focused | No | key press, focused session | a mode change, or a toast | 02 |
| Dashboard API (`dashboard/plugin_api.py`) | Serves and mutates mode over HTTP for the desktop half | No — writes the mode store and one setting | HTTP request | JSON mode payload | 01 |
| Slash command (`/readonly`) | Command-line and desktop command surface | No | argv | status text, or a mode change | 01 |

## 3. Contracts

- **Hook.** `pre_tool_call` returns a deny decision carrying a message that names the active mode
  and the way out. It is registered for every tool, including ones added after it.
- **State file.** JSON object, `{session_id: {mode, renewed_at?, renewed_turn?}}`, at most 200
  sessions, written to a temp file and `os.replace`d into place. `renewed_at` and `renewed_turn`
  exist only on `writable` entries.
- **HTTP.** `GET /state` → `{mode, default, expiry_minutes, session, modes, source}`;
  `POST /state` with `{mode, session?}`; `POST /toggle`. An absent `session` means the default for
  new sessions, never "this machine".
- **Keybinds (02).** Contributions in `KEYBINDS_AREA` with ids `readonly-guard.readonly`,
  `readonly-guard.plan`, `readonly-guard.writable`; defaults `['mod+alt+r']`, `['mod+alt+p']`,
  `[]`; category `Read-only guard`. Rebinding is the host's Settings UI, not a plugin setting.
- **Keybind availability.** The registry belongs to the desktop renderer's plugin SDK, so keybind
  contributions surface only in the Hermes Desktop app. The CLI and TUI have a fixed keymap with
  no plugin registry, gateway platforms have no keyboard, and a browser client has no SDK bridge.
  On every other surface the control is the `/readonly` slash command, which works in all of them.
- **Slash.** `/readonly <readonly|plan|writable|status>`; `status` never mutates.

## 4. Invariants

- I1: a tool call in `readonly` or `plan` that is neither an inspection tool nor a single allowlisted probe is denied before the tool runs.
- I2: a missing, unreadable or unparseable state file resolves every session to `readonly`; no path falls through to allow.
- I3: an exception inside the guard denies the call rather than allowing it.
- I4: a `writable` entry whose lease has lapsed resolves to `readonly`, and no later turn revives it without an explicit re-arm.
- I5: the mode enforced for a session equals the mode `GET /state` reports for it, because both call `effective_mode`.
- I6: `readonly` admits no probe that `plan` refuses.
- I7: the plugin registers the `readonly` keybind with `mod+alt+r` and the `plan` keybind with `mod+alt+p`, and ships `writable` with no default binding.
- I8: a keybind fired while no session is focused changes no state and tells the user why.
- I9: no tool registered by the plugin can change the mode.

## 5. Failure and recovery

| Component | Breaks when | User sees | Recovers by |
|---|---|---|---|
| Guard hook | an import or a probe lookup raises | the call is refused, with the failure named in the message | next call; nothing persists |
| Mode store | the file is a directory, unparseable, or non-object | every session enforces `readonly` | `/readonly writable`, or deleting the file |
| Mode store | Windows holds the file open during replace | the mode change is retried five times over ~300 ms, then the error is surfaced | retry; the old mode still holds |
| Dashboard API | the plugin host is down | the desktop control shows "guard state unavailable" and stays disabled | rescan or restart the app |
| Keybinds (02) | the chord is taken by the OS or another app | the key does nothing, the palette row still works | rebind in Settings, or use the palette |
| Keybinds (02) | nothing focused (empty session) | a toast saying no session is focused | click into a chat, press again |

## 6. Decisions

| ID | Decision | Rejected alternative | Why |
|---|---|---|---|
| D1 | The switch is not an agent tool | a `set_mode` tool | an agent that can turn off its own guard has no guard |
| D2 | Mode is per session, keyed by session id | one global mode | loosening one chat must not unblock another that is still running |
| D3 | `writable` is a lease: 30 minutes of silence, renewed per turn, latched on expiry | a plain latch; a fixed TTL from arming | a latch is a mode users forget; a fixed TTL cuts off long work. Silence is the signal the user walked away |
| D4 | `readonly` runs the same allowlisted probes as `plan` | blocking all execution in `readonly` | "nothing is written" is the useful promise; refusing `ls` makes the mode useless |
| D5 | Fail closed on any state problem, defaulting to `readonly` | fail open with a warning | the failure mode must not be the one the plugin exists to prevent |
| D6 | Keybinds are contributed to the host's keybind registry; the plugin adds no binding setting | a `keybinds:` choice in `config_schema` | the host already renders and persists rebinds; a second store would silently disagree |
| D7 | `mod+alt+r` / `mod+alt+p` / `writable` unbound, desktop only | three chords including `writable`; a single cycle-mode key; binding the CLI too | `mod+alt+letter` is free in Hermes (only `v`, `t`, `n` are taken) and in GNOME (only arrows, Tab, Escape); a writable keystroke arms full access, so it is opt-in; the CLI has no plugin key registry at all |
| D8 | `01` ratifies the shipped guard, `02` carries the keybinds | a single milestone | every `Delivered by` cell must name a milestone that exists, and the guard was not delivered by the keybind milestone |

## 7. Non-goals

- A sandbox. The probe filter is a string filter in front of a shell, and the README says so.
- OS-global hotkeys. Keybinds fire only while the Hermes window has focus; the plugin SDK has no
  path to Electron's `globalShortcut`.
- Keybinds in the CLI, TUI or gateway. Those surfaces have no plugin key registry — the TUI keymap
  is fixed and shared with the classic CLI — so the keyboard interface there is `/readonly`.
- A browser build. The plugin SDK needs the Electron preload bridge; no web package ships in the
  Hermes repo, and a browser client cannot register a keybind.
- Multi-user or remote policy. The mode is one user's, on one machine.
- Network calls, telemetry, and any dependency outside the standard library and Hermes.

## 8. Open questions

- Should a fourth keybind cycle the three modes? Owning milestone: 02, and it ships only if a test can prove the cycle cannot land on `writable` from `readonly` without a deliberate second press.
- Should the countdown also appear in the tooltip as absolute time rather than minutes left? Owning milestone: 02.
