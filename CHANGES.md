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
