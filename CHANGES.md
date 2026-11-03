# Changes

## 2026-11-03 — T008: the probe refuses command substitution in any quoting

`probe_refusal` refused a token that was all shell operators, and a token carrying a backtick,
but `shlex` with `posix=True` removes quoting before the loop sees a token: `cat "$(cmd)"`
arrived as the single token `$(cmd)`, passed both checks, and `/bin/sh` then ran `cmd`. `${…}`
was the same hole with no parenthesis at all, and the unquoted `$(…)` forms were caught only by
accident, because the bare `(` is lexed as an operator token of its own.

A token is now refused when it carries `$(`, `${` or a backtick, in the loop that already
decided composition. The check runs after lexing, so it cannot tell a literal from a
substitution: `cat '$(x)'` is refused too, and searching for a literal `$(` in readonly is
refused with it. Rejected: scanning the raw command string before lexing (the same blind spot,
plus a second parser to keep in step); lexing with `posix=False` so the quotes stay visible
(every other check in the function compares the unquoted token, so that changes every refusal in
the table); and refusing only a token that starts with a marker (it misses `x$(cmd)`, which the
shell still expands).

## 2026-10-30 — T007: the dashboard reports the configured default

`GET /state` answered the constant `readonly` whatever `config.yaml` said. The dashboard half
imports `settings` as a top-level module (it is loaded standalone, not as a package) while
`register()` binds the config reader on the package-relative module: two module objects, two
`_reader`s, and the dashboard's stayed `None`, so `default_mode()` fell back to the constant. With
`default_mode: plan` configured, the guard enforced plan and the chip lit read-only.

It now binds its own reader over Hermes' `plugin_settings_fields` — schema plus current values,
imported lazily so a bare interpreter still imports and reports `readonly` / 30. `settings.py`
keeps the only copy of the validation: a malformed value still reads as `readonly`.

## 2026-10-29 — T001: the keybind registry and the read-only binding

`desktop/plugin.js` now contributes a `KEYBINDS_AREA` clause, so the mode switch has a keyboard
face beside the status-bar chip and the palette rows. Read-only ships bound to `mod+alt+r`.

Rebinding is the host's Settings UI, so the plugin keeps no binding store of its own: a second
store would disagree with the one the user edits. Rejected: a `keybinds:` entry in
`config_schema` (two sources of truth), and a plugin-rendered shortcut editor (the host already
has one).

## 2026-10-29 — T002: the plan binding

Plan ships on `mod+alt+p`. The table is the only place a binding is written, so the two bound
modes cannot drift apart; `mod+alt` is the unused-letter namespace in Hermes (only `v`, `t` and
`n` are taken) and in GNOME (only arrows, Tab and Escape).

## 2026-10-29 — T003: writable ships unbound, and a key with no chat focused does nothing

`writable` is registered with no default binding, and every keybind now refuses when no chat is
focused instead of writing the default for new sessions.

Two rejected designs: binding `writable` to a third chord (one mis-typed key would arm full write
access), and letting `setMode` fall through to the default (it would change every future session
while the user was looking at an empty window).

## 2026-10-29 — T004: pin the rebind contract, add no setting

Two tests now hold the contract the host relies on: `config_schema` carries exactly the two
settings it had, and the three contribution ids are literal strings.

Rejected: storing bindings in the plugin so the CLI could read them too — the CLI has no keybind
registry, and a second store would go stale the first time someone rebinds in Settings.

## 2026-10-29 — T005: the README says where the keybinds work

A `## Keyboard shortcuts` section lists the three actions and a table that names the surfaces
without keybinds — CLI/TUI, gateway, browser — each pointing at `/readonly`.

Rejected: a one-line note under the modes table. A user who presses a key in a terminal needs the
answer where they look for the feature, not in a footnote three sections away.

## 2026-10-30 — T006: the keybind rows render under Session

The contributions now declare `category: 'session'`, a member of the host's `KeybindCategory`
union, instead of the invented `'Read-only guard'`. A test reads that union out of the host's own
source and fails on any category outside it; the README names the same heading.

Why: the Settings panel iterates only the union's members, so the old value registered, fired, and
appeared in no section — reachable only by typing a search term, which left "bind `writable` to a
key of your own" with no route. Rejected: `view`, which would render but is the host's catch-all
for layout and appearance, and a plugin-rendered shortcut editor.

## 2026-10-30 — 3.7: keyboard control

The Desktop app now ships three keybind contributions — `Ctrl+Alt+R` read-only, `Ctrl+Alt+P` plan,
`writable` unbound — registered in the host's keybind registry under the `session` category, so
they appear in Settings → Keybinds and are rebindable there.

Rejected: a plugin-owned binding store (the host already persists rebinds, and two stores
disagree), and binding `writable` by default (one keystroke that arms full write access should be
chosen, not inherited). The category is `session` rather than an invented label because the panel
renders only the five values the host enumerates — an invented one registers, fires, and shows
nowhere.
