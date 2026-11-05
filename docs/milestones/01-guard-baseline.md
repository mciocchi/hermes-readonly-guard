---
schema: milestone/1
architecture: 1
mvp: true
satisfies: [I1, I2, I3, I4, I5, I6, I9]
---

# 01: The guard as shipped

**Goal.** A user can put one session into read-only, plan or writable and watch the guard hold that session to it, with `writable` ending on its own lease.

**Exit.** `python -m unittest discover -s tests -t tests` — `OK`, no failures.

**Out of scope.** Keybinds, catalog listing, Windows CI (all delivered before this document existed; the suite is what ratifies them).

## Features

F1: a user can stop an agent from writing anything in the current chat
F2: a user can let an agent plan, with only the plan markdown writable
F3: a user can grant full access for a bounded time, and it expires on its own
F4: a user can keep two chats in different modes at once
F5: a user can find out which mode is enforced, from the chip, `/readonly status`, or the API

## Tickets

### T007: The dashboard reports the configured default, not a constant

```ticket
id: T007
feature: F5
priority: P0
order: 1
effort: 2
status: done
depends_on: []
files: [dashboard/plugin_api.py, tests/test_dashboard_api.py]
gate: python -m unittest discover -s tests -t tests -p "test_dashboard_api.py"
```

**Context.** Architecture 2 §3 (the HTTP contract: `GET /state` reports
`{mode, default, expiry_minutes, session, modes, source}`, and an absent `session` means the
default that new sessions start with) and §4 invariant I5 (the mode enforced for a session equals
the mode `GET /state` reports for it). This is F5 failing: the chip tells the user read-only while
the guard enforces plan.

The dashboard half imports `settings` as a *top-level* module — `sys.path.insert(0, _PLUGIN_DIR)`
then `from settings import default_mode, writable_expiry_minutes`
(`dashboard/plugin_api.py:29-34`) — while the only `set_reader(ctx.get_config)` call is
`__init__.py:334`, on the *package-relative* module. Hermes loads the agent half as a package
(`spec_from_file_location(..., submodule_search_locations=...)`,
`hermes_cli/plugins_loader.py:718-719`), so those are two different module objects and the
dashboard half's `_reader` is permanently `None`. `default_mode()` (`settings.py:49-53`) then falls
back to `DEFAULT_MODE`, the constant `readonly`, whatever `config.yaml` says.
`writable_expiry_minutes()` is blind the same way and reports 30.

So with `default_mode: plan`, a session with no entry is enforced as plan while `GET /state`
answers `readonly`: the chip lights read-only through turns that are all planned, and a user who
clicks it is operating on a state that disagrees with what is enforced. The write path is honest —
a session-less `POST /state` goes through `save_plugin_settings` — which is how the setting was
changed from a control that then misreported it.

Bind the reader where the dashboard half imports it (`set_reader` on that module), and let
`settings.py` keep the only copy of the validation: a malformed value must still read as
`readonly`, not as whatever the file happened to contain. Import Hermes' config loader lazily,
the way `_write_setting` already imports its writer (`dashboard/plugin_api.py:47-56`), so a bare
test interpreter still imports the module. `plugin.yaml` gains no key. Run the gate under an
interpreter that has `fastapi`: the test module raises `SkipTest` when it does not, and a skip is
not a pass.

**Acceptance**

A1. With `plugins.entries.readonly-guard.settings.default_mode: plan` in a temp `HERMES_HOME` config, `GET /state` with no session returns `mode: plan`, `default: plan`, `source: default`.
A2. Under that same config, `GET /state?session=<an id with no entry>` returns `mode: plan` — the chip's case for a chat that has never been switched.
A3. With `writable_expiry_minutes: 0` in that config, the payload's `expiry_minutes` is `0` and a writable session's `expires_in` is null.
A4. With no Hermes on `sys.path`, the module still imports and reports `readonly` and 30 — the fail-closed fallback, unchanged.
A5. For a session with no entry, the mode `GET /state` reports equals the mode the guard's `resolve_mode` returns under the same config (I5), asserted in one test holding both halves.

**Test plan**

- `tests/test_dashboard_api.py::test_get_without_a_session_reports_the_configured_default` fails first: it expects `plan` and gets the constant `readonly`.
- `tests/test_dashboard_api.py::test_get_for_a_session_with_no_entry_reports_the_configured_default` fails first, for the same reason and on the chip's own path.
- `tests/test_dashboard_api.py::test_a_configured_zero_expiry_is_reported` fails first: 30 is reported instead of 0.
- `tests/test_dashboard_api.py::test_the_reported_default_matches_the_mode_the_guard_enforces` fails first.
- `tests/test_dashboard_api.py::test_the_module_imports_without_hermes_on_the_path` is a pin, green before the change: the lazy import must not turn an absent Hermes into an import error.

#### Review

```review
attempt: 1
verdict: PASS
sha: 1f9a9b9
```

### T008: The probe refuses command substitution in any quoting

```ticket
id: T008
feature: F1
priority: P0
order: 2
effort: 2
status: done
depends_on: []
files: [probe.py, tests/test_probe.py, README.md]
gate: python -m unittest discover -s tests -t tests
```

**Context.** Architecture 2 §2 (Probe filter) and §4 invariant I1, against the claim README line
178 already makes. The catalog review of 3.7 (`a8c518b1`) found that the token loop at
`probe.py:149-153` refuses operator-only tokens and backticks, but `shlex` with `posix=True` strips
quoting before the loop sees a token: `cat "$(cmd)"` arrives as the single token `$(cmd)`. It is
not all operator characters (`_OPERATOR_CHARS` is `();<>|&`, so `$` is not one) and carries no
backtick, so it is admitted, and `/bin/sh` then runs `cmd`. `${…}` is the same hole with no
parenthesis at all: `cat "${HOME}/notes"` is admitted today. The unquoted forms are caught only by
accident, because the bare `(` is lexed as an operator token of its own.

Refuse any token containing `$(`, `${` or a backtick, in the existing token loop, so no second
parse is introduced. The check cannot tell a literal from a substitution once quoting is gone:
`cat '$(x)'` is refused too. That is the conservative direction and A3 pins it deliberately, with
the cost stated: in `readonly`, searching for a literal `$(` is refused (`rg '\$\(' .`).

The reviewer's branch implements this and the flag fix (`hermes-readonly-guard#2`). The acceptance
below is behaviour, so it holds whether the code is written here or taken from that branch.

The attempt-2 review of `fa10a8c` found the class this rule missed: bare `$NAME` is expanded before
the program runs and `IFS` splits the result, so `git log $IFS--output=FILE` reaches git as two
arguments and writes a file while the denied flag is nowhere in the token. Refusing only `$(`, `${`
and the backtick left that open. The rule now refuses any `$` the shell would expand, including the
backslashed form, because the lexer cannot tell `'\$HOME'` from `\\$HOME`; a trailing `$` stays
literal and `[$]` is how a literal dollar is written. The cost is stated: `cat $HOME/notes` and
`rg 'a$b' .` are refused.

Glob expansion is a separate, pre-existing class and is not in this ticket: a file literally named
`--output=x` in the working directory could still inject a flag through `git log *`. Closing it
means deciding whether every unquoted `*` is refused, which breaks legitimate patterns, so it
belongs in its own ticket rather than being smuggled into this rule.

The attempt-3 review left five prose findings, none blocking; they are fixed after the reviewed sha
`4ed4f4e` (the last of those commits is `b97b175`), and the refusal now quotes the whole expansion
(`'$IFS'`) instead of its first letter. The receipt below records the review of `4ed4f4e`, which is
the code the criteria were judged on.

**Acceptance**

A1. `cat "$(cmd)"` and `ls "$(pwd)"` are refused with a reason naming command substitution; `cat $(cmd)` is refused too, by the operator check that already catches its bare `(`.
A2. `cat "${HOME}/notes"` and `ls "${PWD}"` are refused the same way.
A3. `cat '$(not-run)'` is refused too: the refusal runs on lexed tokens, so quoting cannot exempt a literal.
A4. A `$` at the end of a token still passes: `rg -n 'cost$' README.md` and `tr -d '$'` are admitted, and `rg '[$]HOME' .` is too; a backslashed `\$` is not (A6).
A5. The full suite passes with no test that was green before turning red, and `PROBE_PROGRAMS` is unchanged at 29 names.
A6. No token carrying a `$` the shell would expand is admitted: `cat $HOME/notes`, `ls $PWD`, `git log $IFS--output=/tmp/x`, `rg $IFS--pre=id pattern .` and `rg '\$HOME' .` are refused, because `shlex` gives `'\$HOME'` and `\\$HOME` the same token while the second expands unquoted; and `README.md` names `${…}`, `$NAME` and `\$` among the refused expansion.

**Test plan**

- `tests/test_probe.py::test_command_substitution_inside_double_quotes_is_refused` fails first: `cat "$(cmd)"` is admitted today.
- `tests/test_probe.py::test_a_parameter_expansion_is_refused` fails first: `cat "${HOME}/notes"` is admitted today.
- `tests/test_probe.py::test_a_quoted_literal_is_refused_too` fails first: `cat '$(x)'` is admitted today.
- `tests/test_probe.py::test_a_bare_dollar_sign_is_still_allowed` is the pin: its `\$HOME` case moves to `[$]HOME`, and it stays green.
- `tests/test_probe.py::test_a_bare_parameter_expansion_is_refused` fails first: `cat $HOME/notes` is admitted today.
- `tests/test_probe.py::test_a_word_splitting_expansion_cannot_smuggle_a_denied_flag` fails first: `git log $IFS--output=/tmp/x` is admitted and writes a file.
- `tests/test_probe.py::test_a_backslash_before_the_dollar_does_not_exempt_it` fails first: `rg '\$HOME' .` is admitted today.

#### Review

```review
attempt: 3
verdict: PASS
sha: 4ed4f4e
note: gate and mutation probes parent-run at 4ed4f4e (222 tests, OK); the reviewer's session was read-only under the guard it reviewed
```

### T009: The probe refuses a program-running flag in every spelling

```ticket
id: T009
feature: F1
priority: P0
order: 3
effort: 2
status: done
depends_on: [T008]
files: [probe.py, tests/test_probe.py]
gate: python -m unittest discover -s tests -t tests
```

**Context.** Architecture 2 §2 (Probe filter) and §4 invariant I1. The catalog review of 3.7
(`a8c518b1`) filed this as its second finding and the only part of it still open: `sort` denies
`-o` and `--output` (`probe.py:50`) but not `--compress-program`, which runs a program; `rg` denies
`--pre`, `--pre-glob`, `-z` and `--search-zip` (`probe.py:55`) but not `--hostname-bin`. Both are
exact matches on the flag part (`_flag`, `probe.py:158`), and two spellings defeat an exact match:
GNU takes any unambiguous prefix of a long option (`sort --compress-prog=/bin/sh`), and short
options bundle or take an attached value (`sort -uo out`, `sort -oout.txt`).

The command-substitution ticket closed the `$IFS` route into these flags, so what remains is the
literal spellings. The reviewer's branch (`hermes-readonly-guard#2`) claims to carry both this and
the substitution fix; only this half is still missing, so the implementer may verify that branch
rather than invent the code, but the acceptance below is behaviour and holds either way.

Fix the class, not the two entries: one matcher next to `_flag` that decides a token is denied by
its flag part, by being a prefix of a denied long option, or by carrying a denied short flag in a
bundle. `find`'s positive allowlist (`_refuse_unknown_flags`) is untouched: its primaries are
neither abbreviatable nor bundlable, and `find . -name '*.md'` must stay allowed. Rejected:
blocking `$IFS` by name (the substitution rule already covers it, and a name blocklist is a list of
shell constants).

**Acceptance**

A1. `sort --compress-program=/bin/sh in.txt`, `sort --compress-prog=/bin/sh in.txt` and `sort --compress-program /bin/sh in.txt` are refused as not read-only.
A2. `rg --hostname-bin=/bin/sh pattern .` and `rg --hostname-b=/bin/sh pattern .` are refused as not read-only.
A3. A denied short flag is refused inside a bundle and as an attached value: `sort -uo out.txt in.txt`, `sort -oout.txt in.txt`, `tree -Bo out.txt`.
A4. Bundles of allowed flags still pass: `sort -ru in.txt`, `ls -la`, `du -sh .`, `rg -n 'def guard' .`.
A5. The full suite passes with no test that was green before turning red, and `PROBE_PROGRAMS` is unchanged at 29 names.

**Test plan**

- `tests/test_probe.py::test_a_program_running_sort_flag_is_refused_in_every_spelling` fails first: `--compress-program` is admitted today.
- `tests/test_probe.py::test_a_program_running_rg_flag_is_refused_in_every_spelling` fails first: `--hostname-bin` is admitted today.
- `tests/test_probe.py::test_a_denied_short_flag_is_caught_in_a_bundle_or_an_attached_value` fails first: `sort -uo` and `sort -oout.txt` are admitted today.
- `tests/test_probe.py::test_bundles_of_allowed_flags_still_pass` is a pin, green before the change.

#### Review

```review
attempt: 1
verdict: PASS
sha: 8d7c6e7
note: gate and mutations parent-run at 8d7c6e7 (226 OK / 35 OK); the review's medium finding is the git loop, which still exact-matches, so `git grep -nO<prog>` is admitted (pre-existing, outside A1-A5)
```

### T010: The probe refuses a git pager flag in a bundle

```ticket
id: T010
feature: F1
priority: P0
order: 4
effort: 1
status: todo
depends_on: [T009]
files: [probe.py, tests/test_probe.py]
gate: python -m unittest discover -s tests -t tests
```

**Context.** Architecture 2 §2 (Probe filter) and §4 invariant I1. The review of the program-flag
ticket found this while grading `8d7c6e7`: the matcher that ticket added is wired into the reader
loop, but `_git_refusal`'s sub-command loop (`probe.py:258-260`) still compares the flag part with
`in`. `git grep` denies `-O` and `--open-files-in-pager` (`probe.py:78`) because `-O<path>` runs
that program on the matched file, and the attached form defeats the exact match:
`git grep -nOcat -e "def _denied_flag" probe.py` is admitted and runs `cat`, and
`git grep -nO/bin/sh -e x probe.py` would hand the matched file to a shell. The matcher's prefix
branch comes along with `_denied_flag` and costs nothing on this table: every abbreviation it would
catch is one git itself rejects. The live spelling set is the bundle, plus the exact and `=value`
forms the loop already refused.

The bundle rule has one cost: `git grep -ic pattern` is now refused, because the token carries the
`-c` that the loop already refused when it stood alone. `git grep -c` was never admitted, so this
removes an inconsistency rather than a capability; `git grep -i -n pattern` is unchanged.

Scope: only the sub-command loop changes. The global loop at `probe.py:239-243` keeps its exact
match because git parses global options before the sub-command and accepts no bundle spelling
there; if one exists it is its own ticket. The listing tier (`GIT_LISTINGS` through
`_refuse_unknown_flags`) is a positive allowlist and stays exact, the way `find` does.

**Acceptance**

A1. `git grep -nOcat -e probe_refusal probe.py` and `git grep -nO/bin/sh -e x probe.py` are refused as not read-only.
A2. `git grep -O -e probe_refusal probe.py` and `git grep --open-files-in-pager=cat -e x probe.py` stay refused as not read-only.
A3. `git grep -n -e probe_refusal probe.py`, `git log -p -- probe.py` and `git branch -a` stay admitted.
A4. The full suite passes with no test that was green before turning red, and `PROBE_PROGRAMS` is unchanged at 29 names.

**Test plan**

- `tests/test_probe.py::test_a_git_pager_flag_is_refused_in_a_bundle` fails first: `git grep -nOcat` is admitted today.
- `tests/test_probe.py::test_git_grep_and_log_still_read` is a pin, green before the change.
