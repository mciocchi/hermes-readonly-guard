# Changes

## 2026-11-05 — 3.8: the probe refuses five more ways to start a program

Five defects filed against 3.7, each a spelling the probe had already denied in its long form, or an
entry whose only job is to start a child: T008 refuses every `$` expansion rather than only `$(…)`
inside double quotes; T009 denies `sort --compress-program` and `rg --hostname-bin` in the four
spellings a flag has — exact, GNU-prefixed, bundled and attached — through one matcher,
`_denied_flag`; T010 catches `git grep -O` inside a bundle; T011 refuses `git -p`, the alias of the
denied `--paginate`, before a sub-command; T013 drops `git help`, which only starts `man`. T007 is the
one change outside that class: the dashboard reports the configured default instead of a hardcoded
mode.

The rule is bounded by the names in the tables, not by the shell. A program reached through a glob
that expands to a flag-named file, or through a configured textconv driver, is still admitted, and
both are recorded on their tickets. Each entry below carries its own reasoning and the designs that
were rejected.

## 2026-11-05 — T012: the probe refuses a denied flag after an attached value

`_flag` strips `=value` before comparing, so `--git-dir=.git` still matched
`GIT_GLOBAL_VALUE_FLAGS` and the global loop consumed two tokens for a flag that carried one: the
next token was never compared. One attached value therefore hid every name in `GIT_GLOBAL_DENIED`
and the pager alias — `git --git-dir=.git --exec-path=/tmp version`, `--config-env=FOO=BAR`,
`--paginate` and `-p version` were all admitted — and chaining them walked past any number of
denials.

The advance now steps one token when the token itself carries `=`, two only when the value is a
separate token. Rejected: dropping the value flags from `GIT_GLOBAL_VALUE_FLAGS`, which refuses
`git -C /tmp log`, the most common probe there is; and teaching the loop git's grammar per option,
which is the architecture's non-goal.

## 2026-11-05 — T013: the probe refuses `git help`

`git help <command>` sat in the reader table with an empty denied set, so the guard admitted it and
git ran `man`: measured in a read-only session, where the man page for `git-status` was printed, and
under a tty `man` pages through `less`, which runs shell commands from its own prompt. The table's
rule is that a pager is a program — `-O` and `--paginate` are denied for it — so an entry whose only
job is to start one does not belong in it.

Rejected: admitting only `-a`, `-g` and `-c` through the listing tier, which keeps a probe nobody
uses and adds a fourth matching rule; and adding a denied flag to help's empty set, which cannot
work, because the program is the sub-command rather than a flag.

The sweep that justifies stopping here: of the 16 remaining readers and 8 listing sub-commands,
none starts a child unconditionally. The nearest neighbours are the four readers that run a textconv
driver when one is configured (`log`, `diff`, `show`, `whatchanged`) and the tty pager; both are
conditional, which is the ruling that already keeps the auto-pager out of scope. `help` was the only
entry whose only effect is a viewer.

## 2026-11-05 — T011: the probe refuses the pager alias before a git sub-command

`git -p` is git's documented alias for `--paginate`, so it starts the pager the deny list already
refuses: under a tty `GIT_PAGER=<prog> git -p status` runs `<prog>`. The global loop matched the
long name exactly and admitted the alias.

The fix is a second set, `GIT_GLOBAL_ONLY_DENIED`, read only by the global loop. `-p` cannot join
`GIT_GLOBAL_DENIED` because the sub-command loop reads that one too, and after a sub-command `-p`
asks for a patch, so `git log -p` and `git diff -p` would be refused. Rejected: an alias map
`{"-p": "--paginate"}` (the message would name a flag the user never typed), and teaching
`_denied_flag` about aliases (aliases are per-position; `-p` after `log` means patch).

## 2026-11-05 — T010: the probe refuses a git pager flag in a bundle

`git grep -O<prog>` runs that program on every match, and the loop refused its exact and `=value`
spellings while admitting the bundle: `git grep -nOcat` failed the exact match on `-nOcat`, ran
`cat`, and `-O/bin/sh` would have handed the matched file to a shell. The loop now asks the same
`_denied_flag` matcher the reader table uses, once with the sub-command's denied set and once with
the global one, so every spelling the program-flag ticket closed for `sort` and `rg` is closed here
too.

Two tables still match exactly, on purpose: the global option loop, which runs before the
sub-command, and the listing tier, which is a positive allowlist like `find`'s. The bundle rule
costs `git grep -ic`, because the token now carries the `-c` that was refused on its own; `git grep
-c` was already refused, so this removes an inconsistency. Rejected: adding `-O` to the grep entry
alone (the next denied flag reopens the hole), and routing `git grep` through the reader loop (its
sub-command semantics do not fit that table).

## 2026-11-04 — T009: the probe refuses a program-running flag in every spelling

`sort --compress-program=PROG` and `rg --hostname-bin=CMD` both run a program, and neither was in
the denied flags. Both denials are exact matches on the flag part, and three spellings defeat an
exact match: GNU abbreviates a long option to any unambiguous prefix (`sort --compress-prog=`),
short options bundle (`sort -uo out`), and a short option may carry its value attached
(`sort -oout.txt`). A `$IFS` expansion used to reach the same flags and is refused by the
substitution rule, so what was left is the literal spellings.

A matcher beside `_flag` now answers whether a token names a denied flag in any of those spellings,
and the reader loop uses it for every program's denied set, so `file -C` and `tree -o` gained the
bundle forms with no entry of their own. `find` keeps its positive allowlist: its primaries are
neither abbreviatable nor bundlable. Rejected: adding the two flags to the sets and leaving the
matching exact (the next program flag reopens the class), and refusing every token that starts with
`-` (it refuses `sort -ru`, which writes nothing).

## 2026-11-03 — T008: the probe refuses every `$` expansion

`probe_refusal` refused a token that was all shell operators, and a token carrying a backtick,
but `shlex` with `posix=True` removes quoting before the loop sees a token: `cat "$(cmd)"`
arrived as the single token `$(cmd)`, passed both checks, and `/bin/sh` then ran `cmd`. `${…}`
was the same hole with no parenthesis at all, and the unquoted `$(…)` forms were caught only by
accident, because the bare `(` is lexed as an operator token of its own.

A token is now refused when it carries a `$` the shell would expand: `$(`, `${` and a backtick are
command substitution, and any other `$` is an expansion. The second was the hole a review found in
the first fix: `IFS` is a shell constant that splits a word, so `git log $IFS--output=FILE` reached
git as two arguments and wrote a file while the denied flag was nowhere in the token the guard
checked. A `$` at the end of a token stays literal; `[$]` is how a literal dollar is written,
because the backslashed form cannot be exempted: `shlex` gives `'\$HOME'` and `\\$HOME` the same
token, and only the second expands. The check runs after lexing, so `cat '$(x)'` and `cat
$HOME/notes` are refused as well. Rejected: scanning the raw command string before lexing (the same
blind spot, plus a second parser to keep in step); lexing with `posix=False` so the quotes stay
visible (every other check compares the unquoted token); refusing only a token that starts with a
marker (it misses `x$IFS--flag`, which still splits); and allowing the expansions whose names look
harmless (the dangerous one is `IFS`, which every shell carries).

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
