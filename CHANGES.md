# Changes

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
