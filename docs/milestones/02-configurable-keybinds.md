---
schema: milestone/1
architecture: 1
mvp: false
satisfies: [I7, I8]
---

# 02: Keyboard control

**Goal.** A user can switch a session to read-only or plan from the keyboard in the Desktop app, and can rebind those keys and bind `writable` in Settings without editing a file.

**Exit.** With the desktop focused and a chat open: `Ctrl+Alt+R` fills the read-only pill, `Ctrl+Alt+P` fills the plan pill, and Settings → Keybinds lists all three actions under "Read-only guard" with `writable` showing no binding.

**Out of scope.** OS-global hotkeys; a cycle-mode key; keybinds in the CLI, TUI, gateway or a browser client — those surfaces expose `/readonly` instead, because the desktop keybind registry is not available to them.

## Features

F1: a user can switch the focused session to read-only with a keystroke
F2: a user can switch the focused session to plan with a keystroke
F3: a user can bind `writable` to a key of their own, and it ships unbound
F4: a user can rebind any of the three in Settings and have it survive a restart
F5: a user reading the README can tell which surfaces have keybinds, and what to use on the others

## Tickets

### T001: The keybind registry and the read-only binding

```ticket
id: T001
feature: F1
priority: P0
order: 1
effort: 3
status: in_progress
depends_on: []
files: [desktop/plugin.js, tests/test_desktop_contract.py]
gate: python -m unittest discover -s tests -t tests -p "test_desktop_contract.py"
```

**Context.** Architecture 1, component "Keybind contributions", invariants I7 and I8. The registry
is the desktop renderer's: `KEYBINDS_AREA` beside `PALETTE_AREA` in `@hermes/plugin-sdk`, with
`data: {id, label, category, defaults, run}`. `run` reuses the existing
`setMode(mode, session)` at `desktop/plugin.js:63`. Rebindability is the host's Settings UI
(decision D6), so this ticket adds no `config_schema` key.

**Acceptance**

A1. `desktop/plugin.js` imports `KEYBINDS_AREA` from `@hermes/plugin-sdk` and registers one contribution in `area: KEYBINDS_AREA` with `id: 'readonly-guard.readonly'`.
A2. That contribution's `defaults` is exactly `['mod+alt+r']`, and its `label` and `category` are set (category `Read-only guard`).
A3. The contribution's `run` calls the file's existing `setMode` with `'readonly'`.
A4. The SDK barrel exports `KEYBINDS_AREA` — the existing barrel check must pass, not be skipped.

**Test plan**

- `tests/test_desktop_contract.py::test_the_read_only_keybind_is_registered_with_its_default` fails first.
- `tests/test_desktop_contract.py::test_the_keybind_area_is_an_sdk_constant` fails first on a string literal `'keybinds'`.

#### Review

```review
attempt: 1
verdict: FAIL_CODE
sha: 8f7ed25
note: category 'Read-only guard' is outside the host's KeybindCategory union, so no row renders in Settings -> Keybinds
```
### T002: The plan binding

```ticket
id: T002
feature: F2
priority: P0
order: 2
effort: 1
status: done
depends_on: [T001]
files: [desktop/plugin.js, tests/test_desktop_contract.py]
gate: python -m unittest discover -s tests -t tests -p "test_desktop_contract.py"
```

**Context.** Architecture 1, I7. The second row of the table T001 introduced; the table is the
only place a binding is written.

**Acceptance**

A1. A second contribution with `id: 'readonly-guard.plan'` exists in `area: KEYBINDS_AREA`.
A2. Its `defaults` is exactly `['mod+alt+p']`.
A3. Its `run` calls `setMode` with `'plan'`.
A4. The two bindings do not share a default.

**Test plan**

- `tests/test_desktop_contract.py::test_the_plan_keybind_is_registered_with_its_default` fails first.

#### Review

```review
attempt: 1
verdict: PASS
sha: 4c2638b
```
### T003: The writable action, unbound, and the no-session refusal

```ticket
id: T003
feature: F3
priority: P0
order: 3
effort: 3
status: in_progress
depends_on: [T002]
files: [desktop/plugin.js, tests/test_desktop_contract.py]
gate: python -m unittest discover -s tests -t tests -p "test_desktop_contract.py"
```

**Context.** Architecture 1, I7 and I8. `writable` ships with `defaults: []` — a keystroke that
arms full write access is opt-in (decision D7). And a keybind fired with no focused session must
not fall through to "default for new sessions": `setMode('writable')` with an empty session writes
the setting for all new chats, which is a surprising side effect for a key press.

**Acceptance**

A1. A third contribution with `id: 'readonly-guard.writable'` exists in `area: KEYBINDS_AREA`.
A2. Its `defaults` is exactly `[]`.
A3. Its `run` resolves the focused session first and returns without calling `setMode` when there is none.
A4. In that case it calls `host.notify` with a message naming the missing session.
A5. `setMode` is still reached when a session is focused.

**Test plan**

- `tests/test_desktop_contract.py::test_writable_ships_unbound` fails first.
- `tests/test_desktop_contract.py::test_a_keybind_with_no_focused_session_does_not_change_state` fails first.

#### Review

```review
attempt: 1
verdict: FAIL_CODE
sha: 025b5e3
note: F3 unreachable for the same reason: the category matches no section; the fix is the architecture's contract first (BOUNCE_SPEC)
```
### T004: The host owns the rebind store

```ticket
id: T004
feature: F4
priority: P1
order: 4
effort: 2
status: done
depends_on: [T003]
files: [tests/test_packaging.py, plugin.yaml]
gate: python -m unittest discover -s tests -t tests -p "test_packaging.py"
```

**Context.** Architecture 1, decision D6: the host persists rebinds against the contribution id, so
(a) the ids must be stable literals — a derived or renamed id silently drops a user's rebind after
an upgrade — and (b) the plugin must not add a `keybinds:` setting that would compete with Settings.
`plugin.yaml` gains no key: this ticket is mostly a guard, and the test is the deliverable. No
version bump happens in this milestone; the release pass is separate.

**Acceptance**

A1. The three contribution ids appear in `desktop/plugin.js` as string literals, not built from a variable.
A2. `plugin.yaml`'s `config_schema` declares exactly `default_mode` and `writable_expiry_minutes` — a third key fails the test.
A3. The three ids are distinct.

**Test plan**

- `tests/test_packaging.py::test_the_plugin_adds_no_keybind_setting` fails first if a keybind key is ever added.
- `tests/test_packaging.py::test_the_keybind_ids_are_literal_strings` fails first on a derived id.

#### Review

```review
attempt: 1
verdict: PASS
sha: 063ddf3
```
### T005: The README says where the keys do not work

```ticket
id: T005
feature: F5
priority: P1
order: 5
effort: 2
status: done
depends_on: [T003]
files: [README.md, tests/test_readme.py]
gate: python -m unittest discover -s tests -t tests -p "test_readme.py"
```

**Context.** Architecture 1, invariant I7 and §7 non-goals. A user who presses a key in the terminal
needs an answer in the document they already have. `/readonly` is the cross-surface control and
works in CLI, TUI, desktop and gateway sessions. Add the section as `## Keyboard shortcuts` between
`## Switching it` and `## The default for new sessions`, and add it to `SECTIONS` in the same commit.

**Acceptance**

A1. `README.md` has a `## Keyboard shortcuts` section listing the three actions with `Ctrl+Alt+R`, `Ctrl+Alt+P` and `writable` as unbound.
A2. Within that section, a table names `Desktop app`, `CLI and TUI`, `Gateway sessions` and `A browser client`, with `/readonly` as the fallback row for the last three.
A3. The section contains no `<kbd>` tag — `HTML_TAG_RE` fails any HTML the docs renderer would drop.
A4. `SECTIONS` in `tests/test_readme.py` lists the new heading in position.
A5. The full suite passes, not only `test_readme.py`.

**Test plan**

- `tests/test_readme.py::test_the_keyboard_shortcuts_section_scopes_itself_to_the_desktop_app` fails first.
- `tests/test_readme.py::test_the_sections_a_reader_needs_are_present_in_order` fails first when the heading is added without `SECTIONS`.

#### Review

```review
attempt: 1
verdict: PASS
sha: 7713fb8
note: README claims verified; the milestone Exit is a keystroke and remains unverified
```
