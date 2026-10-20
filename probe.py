"""Which shell commands plan mode may run through ``terminal``.

Plan mode is where a plan gets written, and a plan worth anything needs to read the
repo: recent history, a file that has already moved, the tree's shape. Blocking
``terminal`` entirely turned that into a round trip through the user, so this module
admits a narrow class of command instead: one program, no shell composition, and
nothing the program can do that writes, executes, or waits.

It is a speed bump, not a sandbox. Every verdict is a decision about a string that
``/bin/sh`` will then interpret, so a hole here is a hole in the guard: anything
unrecognised is refused, and each table errs towards refusing a useful command.
"""

from __future__ import annotations

import shlex

#: `shlex` splits these out as their own tokens when `punctuation_chars` is on —
#: but only outside quotes, which is why a quoted pipe is allowed and a bare one is not.
_OPERATOR_CHARS = frozenset("();<>|&")

#: Arguments a probe may carry. Anything else turns the call into a process or a
#: notification (`background`, `pty`, `notify`, `heartbeat`, `persist_on_release`,
#: and the legacy `notify_on_complete` / `watch_patterns`).
_PROBE_ARG_KEYS = frozenset({"command", "workdir", "timeout"})

#: Programs that only read, with the flags that stop them doing even that.
#: A flag is compared before any `=value`, so `--output=x` is caught by `--output`.
READERS: dict[str, frozenset[str]] = {
    "ls": frozenset(),
    "cat": frozenset(),
    "head": frozenset(),
    "tail": frozenset({"-f", "--follow", "-F", "--retry"}),      # follow = never returns
    "wc": frozenset(),
    "file": frozenset(),
    "stat": frozenset(),
    "pwd": frozenset(),
    "tree": frozenset({"-o"}),                                    # -o writes a file
    "du": frozenset(),
    "df": frozenset(),
    "ps": frozenset(),
    "uname": frozenset(),
    "whoami": frozenset(),
    "id": frozenset(),
    "which": frozenset(),
    "realpath": frozenset(),
    "readlink": frozenset(),
    "cut": frozenset(),
    "tr": frozenset(),
    "sort": frozenset({"-o", "--output"}),
    "nl": frozenset(),
    "column": frozenset(),
    "diff": frozenset(),
    "grep": frozenset(),
    "rg": frozenset({"--pre", "--pre-glob", "-z", "--search-zip"}),  # both spawn a program
    "jq": frozenset(),
}

#: `find` admits only these primaries: one missed `-exec`/`-delete`/`-fprintf` and the
#: program is a mutation tool, so this is an allowlist rather than a blacklist.
FIND_FLAGS: frozenset[str] = frozenset({
    "-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-lname",
    "-type", "-size", "-newer", "-mtime", "-mmin", "-user", "-group", "-perm", "-links",
    "-maxdepth", "-mindepth", "-fstype", "-samefile",
    "-empty", "-readable", "-writable", "-executable",
    "-print", "-print0", "-depth", "-prune", "-quit", "-not", "-and", "-or",
})

#: `git` sub-commands that cannot mutate on a positional argument, with the flags that
#: would let them write a file or run a program anyway.
GIT_READERS: dict[str, frozenset[str]] = {
    "status": frozenset(),
    "log": frozenset({"--output", "--ext-diff", "--textconv"}),
    "diff": frozenset({"--output", "--ext-diff", "--textconv"}),
    "show": frozenset({"--output", "--ext-diff", "--textconv"}),
    "shortlog": frozenset({"--output"}),
    "blame": frozenset({"--output"}),
    "grep": frozenset({"-O", "--open-files-in-pager"}),          # a pager is a program
    "rev-parse": frozenset(),
    "ls-files": frozenset(),
    "ls-tree": frozenset(),
    "cat-file": frozenset(),
    "describe": frozenset(),
    "for-each-ref": frozenset(),
    "show-ref": frozenset(),
    "whatchanged": frozenset({"--output", "--ext-diff", "--textconv"}),
    "version": frozenset(),
    "help": frozenset(),
}

#: Sub-commands that are safe *only* as a listing: the first word after the
#: sub-command must be one of these, and no positional may follow it. That is why
#: `git branch -a` is allowed and `git branch new-thing` is not.
GIT_LISTINGS: dict[str, frozenset[str]] = {
    "branch": frozenset({"-l", "--list", "-a", "--all", "-r", "--remotes", "-v", "--verbose",
                         "--show-current"}),
    "tag": frozenset({"-l", "--list"}),
    "stash": frozenset({"list", "show"}),
    "remote": frozenset({"-v", "--verbose", "show"}),
    "worktree": frozenset({"list"}),
    "notes": frozenset({"list"}),
    "reflog": frozenset({"show"}),
    "submodule": frozenset({"status", "summary"}),
}

#: Global flags that take the NEXT token as their value. The loop has to consume that
#: token, or `git -C /tmp log` reads `/tmp` as the sub-command and refuses the most
#: common probe there is.
GIT_GLOBAL_VALUE_FLAGS: frozenset[str] = frozenset({"-C", "--git-dir", "--work-tree",
                                                   "--namespace", "--super-prefix"})

#: Refused anywhere in a `git` command line: config injection (`-c alias.x='!cmd' x`),
#: an alternate `--exec-path`, and pager execution.
GIT_GLOBAL_DENIED: frozenset[str] = frozenset(
    {"-c", "--config-env", "--exec-path", "--paginate"}
)

#: Every program a probe may run — derived from the tables, never re-listed, so a
#: program added above cannot go missing from the message the user reads.
PROBE_PROGRAMS: frozenset[str] = frozenset(READERS) | {"find", "git"}


def _flag(token: str) -> str:
    """A token's flag part: `--output=x` -> `--output`."""
    return token.split("=", 1)[0]


def probe_refusal(args: object) -> str | None:
    """None when *args* is a probe command, else a one-line reason it is not."""
    if not isinstance(args, dict):
        return "terminal needs a mapping of arguments"
    extra = sorted(set(args) - _PROBE_ARG_KEYS)
    if extra:
        return f"{', '.join(extra)} is not part of a probe — no background job, no pty"
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        return "terminal needs a command string"
    if "\n" in command or "\r" in command:
        return "multiple lines are not a probe — one command only"
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return "the command cannot be parsed (unbalanced quoting)"
    if not tokens:
        return "terminal needs a command string"
    for token in tokens:
        if token and set(token) <= _OPERATOR_CHARS:
            return f"shell operator {token!r} is not allowed — one command, no composition"
        if "`" in token:
            return "command substitution is not allowed"
    program, rest = tokens[0], tokens[1:]
    if program == "find":
        return _refuse_unknown_flags(rest, FIND_FLAGS, "find")
    if program == "git":
        return _git_refusal(rest)
    denied = READERS.get(program)
    if denied is None:
        return f"{program!r} is not a probe command"
    for token in rest:
        if _flag(token) in denied:
            return f"{program} {_flag(token)} is not read-only"
    return None


def _refuse_unknown_flags(tokens: list[str], allowed: frozenset[str], name: str) -> str | None:
    """Refuse any flag outside *allowed*; bare words are paths or argument values."""
    for token in tokens:
        if token.startswith("-") and _flag(token) not in allowed:
            return f"{name} {_flag(token)} is not on the probe allowlist"
    return None


def _git_refusal(tokens: list[str]) -> str | None:
    """Refuse anything but a read-only `git` sub-command (and its read-only flags)."""
    index = 0
    while index < len(tokens) and tokens[index].startswith("-"):
        flag = _flag(tokens[index])
        if flag in GIT_GLOBAL_DENIED:
            return f"git {flag} is not allowed — it can run a command or inject config"
        index += 2 if flag in GIT_GLOBAL_VALUE_FLAGS else 1
    if index >= len(tokens):
        return "git needs a sub-command"
    sub, rest = tokens[index], tokens[index + 1:]
    if sub in GIT_LISTINGS:
        tier = GIT_LISTINGS[sub]
        if not rest or rest[0] not in tier:
            allowed = ", ".join(sorted(tier))
            return f"git {sub} is allowed as a listing only ({allowed}), with no extra arguments"
        if any(not token.startswith("-") for token in rest[1:]):
            return f"git {sub} listing takes no positional arguments"
        return _refuse_unknown_flags(rest[1:], tier, f"git {sub}")
    denied = GIT_READERS.get(sub)
    if denied is None:
        return f"git {sub} is not a read-only sub-command"
    for token in rest:
        if token.startswith("-") and (_flag(token) in denied or _flag(token) in GIT_GLOBAL_DENIED):
            return f"git {sub} {_flag(token)} is not read-only"
    return None
