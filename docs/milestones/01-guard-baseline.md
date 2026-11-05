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
178 already makes. The catalog review of 3.7 (`a8c518b1`) found that the token loop in
`probe_refusal` refuses operator-only tokens and backticks, but `shlex` with `posix=True` strips
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
(`a8c518b1`) filed this as its second finding and the only part of it still open: `sort` denied
`-o` and `--output` but not `--compress-program`, which runs a program; `rg` denied `--pre`,
`--pre-glob`, `-z` and `--search-zip` but not `--hostname-bin`. Both were exact matches on the flag
part, and two spellings defeat an exact match:
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
status: done
depends_on: [T009]
files: [probe.py, tests/test_probe.py]
gate: python -m unittest discover -s tests -t tests
```

**Context.** Architecture 2 §2 (Probe filter) and §4 invariant I1. The review of the program-flag
ticket found this while grading `8d7c6e7`: the matcher that ticket added is wired into the reader
loop, but `_git_refusal`'s sub-command loop still compares the flag part with
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

Scope: only the sub-command loop changes. The global loop in `_git_refusal` keeps its exact
match because git parses global options before the sub-command and accepts no bundle spelling
there; if one exists it is its own ticket. The listing tier (`GIT_LISTINGS` through
`_refuse_unknown_flags`) is a positive allowlist and stays exact, the way `find` does.

The review left three low findings. Two are fixed after the reviewed sha `2d22180` (last of them
`c1eb6aa`): the global loop now carries the comment that says why it keeps the exact match, and the
pin freezes both sides of the bundle rule's `-c` cost. The third is left alone: the pin repeats
`git branch -a` and `git log`, which costs microseconds and protects nothing more.

A review of those commits at `dc00080` returned `PASS` and found one pre-existing hole of the same
class, which needs its own ticket: `-p` is git's alias for the denied `--paginate` and is admitted,
while adding `-p` to the shared set would refuse `git log -p` and `git diff -p`. The two prose
defects it found here — stale `probe.py` line refs and a claimed second of runtime — are fixed in
the commits after `dc00080`.

**Acceptance**

A1. `git grep -nOcat -e probe_refusal probe.py` and `git grep -nO/bin/sh -e x probe.py` are refused as not read-only.
A2. `git grep -O -e probe_refusal probe.py` and `git grep --open-files-in-pager=cat -e x probe.py` stay refused as not read-only.
A3. `git grep -n -e probe_refusal probe.py`, `git log -p -- probe.py` and `git branch -a` stay admitted.
A4. The full suite passes with no test that was green before turning red, and `PROBE_PROGRAMS` is unchanged at 29 names.

**Test plan**

- `tests/test_probe.py::test_a_git_pager_flag_is_refused_in_a_bundle` fails first: `git grep -nOcat` is admitted today.
- `tests/test_probe.py::test_git_grep_and_log_still_read` is a pin, green before the change.

#### Review

```review
attempt: 1
verdict: PASS
sha: 2d22180
note: gate (228 OK) and both mutations parent-run at 2d22180; reviewer session read-only under the guard it reviewed, so the suite was not re-run here
```

### T011: The probe refuses the pager alias before a git sub-command

```ticket
id: T011
feature: F1
priority: P0
order: 5
effort: 2
status: done
depends_on: [T010]
files: [probe.py, tests/test_probe.py, CHANGES.md]
gate: python -m unittest discover -s tests -t tests
```

**Context.** Architecture 2 §2 (Probe filter) and §4 invariant I1. The review of the polish commits
at `dc00080` found this while listing the global loop's hand-written match: `-p` is git's
documented alias for `--paginate`, and `GIT_GLOBAL_DENIED` denies the long name
alone. Measured on this host: `probe_refusal({"command": "git -p status --short"})` returns `None`
while `git --paginate status --short` is refused, and under a tty
`GIT_PAGER="touch <file>" git -p status` creates the file and exits 0, so the alias does run the
configured program.

The fix is not a line in `GIT_GLOBAL_DENIED`. Both loops consult that set — the global one, and the
sub-command one through `for denied_set in (denied, GIT_GLOBAL_DENIED)` — so `-p` in it also
refuses `git log -p` and `git diff -p`, where `-p` means patch
and is read-only. Measured by adding `-p` to the set at run time: `git log -p -- probe.py` then
answers "git log -p is not read-only", and that command is the pager ticket's A3. The alias needs a
set only the global loop consults, or an alias map applied there alone; either shape is acceptable,
and the sub-command loop must not see `-p`.

Two neighbours, so the next reader does not re-open them. `git -cuser.name=x status` is admitted
because the exact match does not split an attached value, and git rejects that spelling itself
(exit 129, "unknown option"), so no program runs. `git -P` and `--no-pager` are the safe twins and
stay admitted. The scope is aliases, not spellings: `_denied_flag` cannot reach this one, because
`-p` is not an abbreviation, a bundle or an attached value of `--paginate`. Out of scope is what
the pager does once it starts — `less` runs shell commands from its own prompt — because the guard
promises that the command spawns no second program, not that the first one is harmless.

The review at `eb7d15d` returned `PASS` and found one high defect that predates this ticket and that
no criterion names: the global loop skips the token after any value flag, and `_flag` strips
`=value`, so `git --git-dir=.git --exec-path=/tmp version` is admitted and the denial never sees the
second flag. Reproduced at `5225095`: `git --git-dir=.git -p version`, `--paginate version`,
`--exec-path=/tmp version` and `--config-env=FOO=BAR version` all return `None`, while
`git --git-dir=.git -c user.name=x version` is refused only because the config string is read as the
sub-command. It needs its own ticket; this ticket's denial is correct for the token the loop reaches.

Two lows are fixed after the reviewed sha, in `ac28283` and `5beea6f`: the refusal now names the
pager as a third cause, since `-p` starts it and neither runs a command nor injects config, and the
program-flag ticket's sentence is past tense without line references, because the lines it cited now
contain the flags it said were missing.

**Acceptance**

A1. `git -p status --short` is refused, and the reason names `-p`.
A2. `git -P status --short` and `git --no-pager log --oneline -1` stay admitted.
A3. `git log -p -- probe.py` and `git diff -p HEAD~1` stay admitted.
A4. `git --paginate status --short`, `git -c user.name=x status` and `git grep -ic pattern` stay refused.
A5. The full suite passes with no test that was green before turning red, and `PROBE_PROGRAMS` is unchanged at 29 names.

**Test plan**

- `tests/test_probe.py::test_the_pager_alias_is_refused` fails first: `git -p status --short` is admitted today.
- `tests/test_probe.py::test_patch_flags_stay_read_only` is a pin, green before the change.
- `tests/test_probe.py::test_git_grep_and_log_still_read` already pins the `-ic` half of A4.

#### Review

```review
attempt: 1
verdict: PASS
sha: eb7d15d
note: gate (230 OK at 16d1a5f) and scoped suite (39 OK at 68b15fa) parent-run, both mutations noticed; finding 1 (high, pre-existing) is a live bypass of every global denial through an attached-value prefix, outside A1-A5
```

### T012: The probe refuses a denied flag that follows an attached value

```ticket
id: T012
feature: F1
priority: P0
order: 6
effort: 2
status: todo
depends_on: [T011]
files: [probe.py, tests/test_probe.py, CHANGES.md]
gate: python -m unittest discover -s tests -t tests
```

**Context.** Architecture 2 §2 (Probe filter) and §4 invariant I1. The review of the pager-alias
ticket at `eb7d15d` found this while reading the global loop: `_flag()` strips a `=value` before
comparing, so an attached value still matches `GIT_GLOBAL_VALUE_FLAGS`, and the loop advances two
tokens for a flag that carried only one. The token after it is never compared.

Reproduced at `5225095` through `probe_refusal`, each of these returning `None`:

    git --git-dir=.git --exec-path=/tmp version
    git --git-dir=.git --config-env=FOO=BAR version
    git --git-dir=.git --paginate version
    git --git-dir=.git -p version

`git --git-dir=.git -c user.name=x version` is refused, but for the wrong reason: the config string
is read as the sub-command. So three of the four names in `GIT_GLOBAL_DENIED` and the one alias in
`GIT_GLOBAL_ONLY_DENIED` are one attached value away from being bypassed.

The repair is the advance, not the table: step one token when the token itself carries `=`, and two
only when the value is a separate token. The obvious alternative — dropping `--git-dir` and friends
from `GIT_GLOBAL_VALUE_FLAGS` — refuses `git --git-dir /tmp/x log`, and `git -C /tmp log` is the
most common probe there is. One site changes: the global loop. The sub-command loop and
`_refuse_unknown_flags` compare every token and skip none, so neither has this shape.

The sweep this ticket was widened by: the skip belongs to every value flag, not to `--git-dir`
alone. Measured at `5225095`, each of these returns `None` as well:

    git --work-tree=. --exec-path=/tmp version
    git --namespace=x --paginate version
    git --super-prefix=x -p version
    git -C /tmp --git-dir=.git --exec-path=/tmp version

The last one shows the skip compounding: each attached value steps over the token after it, so a
chain of them walks past any number of denied globals. `-C` is not in A1's list because it has no
attached form git accepts: `git -C/tmp log` exits 129 with "unknown option". It also re-admits a
command another ticket closed: `git --git-dir=.git help status` returns `None`, so the git-help
ticket's refusal holds only for the bare spelling.

Scope: the attached-value spelling of a value flag, and nothing else. The alias and the bundle work
are done; `-p` appears here only because the skip also hides it. Checked and left alone, so the next
reader does not re-open them:

- `git --git-dir=.git -cuser.name=x version` is admitted, because `_flag` yields `-cuser.name`,
  which is neither `-c` nor a value flag. git rejects that spelling itself (exit 129, "unknown
  option"), so no program runs; refusing it would be a rule about a spelling git never executes.
- `git --git-dir=.git --version` is refused as a missing sub-command. That is a false refusal, not a
  bypass, and the same refusal fires on `git --version` alone.
- `git help <command>` is admitted and starts `man` or a viewer. That is a table defect of the
  `--paginate` kind, not the scanner's, and it needs its own ticket.

**Acceptance**

A1. For each of `--git-dir`, `--work-tree`, `--namespace` and `--super-prefix`, a denied global placed after that flag in its attached form is refused as not allowed, and the two-flag chain `git -C /tmp --git-dir=.git --exec-path=/tmp version` is refused too.
A2. `git -C /tmp -p log`, `git --git-dir=.git -p log` and `git --work-tree=. -p version` are refused, and the reason names `-p`.
A3. `git --git-dir=.git log`, `git --git-dir /tmp/x log`, `git --work-tree /tmp log`, `git -C /tmp log` and `git -C /tmp log --oneline -3` stay admitted.
A4. `git --git-dir=.git -c user.name=x version` is refused, and the reason names `-c`.
A5. The full suite passes with no test that was green before turning red, and `PROBE_PROGRAMS` is unchanged at 29 names.

**Test plan**

- `tests/test_probe.py::test_a_denied_flag_after_an_attached_value_is_refused` fails first: the loop skips the token after an attached value, so every command in A1 is admitted today.
- `tests/test_probe.py::test_value_flags_still_consume_a_separate_value` is a pin, green before the change.
- `tests/test_probe.py::test_the_pager_alias_is_refused` keeps the unattached alias forms green.

### T013: The probe refuses git help, which only starts a viewer

```ticket
id: T013
feature: F1
priority: P1
order: 7
effort: 1
status: done
depends_on: []
files: [probe.py, tests/test_probe.py, CHANGES.md]
gate: python -m unittest discover -s tests -t tests
```

**Context.** Architecture 2 §2 (Probe filter) and §4 invariant I1. `GIT_READERS` carries
`"help": frozenset()`, so `git help <command>` is an admitted probe whose only purpose is to start
a viewer. Measured in a read-only session of this plugin: `probe_refusal({"command": "git help
status"})` returned `None`, the command then executed `/usr/bin/man`, and the man page for
`git-status` was printed. Under a tty `man` pages through `less`, which can run shell commands from
its own prompt. The table's rule is that starting a program is a denial — `-O` and `--paginate` are
refused for exactly that — so an entry that always starts one does not belong in it.

The ruling at architecture v2: `git help <command>` is documentation, not repo inspection, so the
entry goes. Rejected: keeping the entry and tiering it like `git branch -a`, admitting only `-a`,
`-g` or `-c` as the first argument — it keeps a probe nobody uses and adds a fourth matching rule
to the file. Rejected too: adding a denied flag to help's empty set, which cannot help, because the
program here is the sub-command itself rather than a flag.

Out of scope: the auto-pager on `git log` and `git diff` under a tty. Nothing pages in the guard's
own execution context, and the pager-alias ticket records that measurement; reaching for it here
reopens that ticket, not this one.

The review at `eec3a45` returned `PASS` and swept both tables: 16 readers and 8 listing
sub-commands, none of which starts a child unconditionally. The four readers that run a textconv
driver when one is configured, and the tty pager, are the nearest neighbours and both are
conditional, which is why `help` was the only entry whose only effect is a viewer. Two lows are
fixed after the reviewed sha: `git version` is pinned with the other read-only sub-commands
(`978c2c3`), and the changelog carries the sweep. The bare spelling is what this ticket closes;
`git --git-dir=.git help status` is still admitted through the attached-value skip, which is the
attached-value ticket's to close.

**Acceptance**

A1. `git help status` is refused, and the reason says it is not a read-only sub-command.
A2. `git help -a` and `git help -g` are refused the same way.
A3. `git version`, `git status --short`, `git log -1` and `git grep -n def` keep their current verdicts.
A4. The full suite passes with no test that was green before turning red, and `PROBE_PROGRAMS` is unchanged at 29 names.

**Test plan**

- `tests/test_probe.py::test_git_help_is_refused` fails first: `git help status` is admitted today.
- `tests/test_probe.py::test_read_only_subcommands_are_allowed` is a pin for the git half of A3, green before the change.

#### Review

```review
attempt: 1
verdict: PASS
sha: eec3a45
note: gate (231 OK) and both mutations parent-run; the sweep found no second entry that starts a child unconditionally, and `git --git-dir=.git help status` still walks past it until the attached-value ticket lands
```
