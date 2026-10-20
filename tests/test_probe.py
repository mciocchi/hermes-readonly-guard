"""probe.py: which shell commands plan mode may run.

The refusals matter more than the allows: each one is a way a shell command could
stop being a read. ``probe_refusal`` returns None for an allowed command and a short
reason otherwise, and every case here is a single call, so a failure names the exact
command that got the wrong verdict.
"""

from __future__ import annotations

import unittest

from plugin_under_test import load_submodule

probe = load_submodule("probe")


def refusal(command, **extra):
    return probe.probe_refusal({"command": command, **extra})


class ProbeTestCase(unittest.TestCase):
    def assertAllowed(self, command, **extra):
        self.assertIsNone(refusal(command, **extra), command)

    def assertRefused(self, command, fragment=None, **extra):
        reason = refusal(command, **extra)
        self.assertIsNotNone(reason, command)
        if fragment is not None:
            self.assertIn(fragment, reason, f"{command!r} -> {reason!r}")


class TestAllowed(ProbeTestCase):
    def test_read_only_commands_are_allowed(self):
        for command in (
            "git status",
            "git status --short",
            "git log --oneline -20",
            "git log -p -- src/app.py",
            "git diff HEAD~1 --stat",
            "git show 621acf6",
            "git blame README.md",
            "git rev-parse --show-toplevel",
            "git ls-files",
            "git branch -a",
            "git tag -l",
            "git stash list",
            "git remote -v",
            "git worktree list",
            "ls -la",
            "cat README.md",
            "head -40 tests/test_probe.py",
            "tail -5 CHANGELOG.md",
            "wc -l probe.py",
            "rg 'probe_refusal' .",
            "rg 'foo|bar' .",              # a quoted pipe is text, not a pipe
            "grep -rn 'def guard' .",
            "find . -name '*.py' -type f",
            "find . -maxdepth 2 -name '*.md'",
            "file README.md",
            "stat README.md",
            "du -sh .",
            "df -h",
            "ps aux",
            "jq '.version' package.json",
        ):
            self.assertAllowed(command)

    def test_workdir_and_timeout_are_allowed_arguments(self):
        self.assertIsNone(
            probe.probe_refusal({"command": "git log", "workdir": "/tmp", "timeout": 30})
        )


class TestShellComposition(ProbeTestCase):
    def test_command_chaining_is_refused(self):
        for command in (
            "git log; rm -rf /",
            "git log && curl example.com",
            "git log || rm -rf /",
            "ls & rm -rf /",
        ):
            self.assertRefused(command, "operator")

    def test_pipes_are_refused(self):
        self.assertRefused("rg foo|bar .", "operator")
        self.assertRefused("git log | tee out.txt", "operator")

    def test_redirection_is_refused(self):
        for command in ("git log > out.txt", "cat x >> y", "cat < /etc/passwd"):
            self.assertRefused(command, "operator")

    def test_command_substitution_is_refused(self):
        for command in ("git log $(rm -rf /)", "cat `rm -rf /`", "ls $(whoami)"):
            self.assertRefused(command)

    def test_newlines_are_refused(self):
        self.assertRefused("git log\nrm -rf /", "multiple lines")
        self.assertRefused("git log\rrm -rf /", "multiple lines")

    def test_unbalanced_quoting_is_refused(self):
        self.assertRefused("cat 'unterminated", "parse")


class TestPrograms(ProbeTestCase):
    def test_mutating_or_executing_programs_are_refused(self):
        for command in (
            "rm -rf /tmp/x",
            "cp a b",
            "mv a b",
            "mkdir x",
            "touch x",
            "chmod +x probe.py",
            "ln -s a b",
            "tee out.txt",
            "sed -i 's/a/b/' file",
            "sed -n '1p' file",             # refused for now: excluded wholesale
            "awk '{print}' file",
            "python3 -c 'open(\"x\",\"w\")'",
            "python -m http.server",
            "node -e 'require(\"fs\")'",
            "perl -e 'unlink 1'",
            "bash -c 'ls'",
            "sh -c 'ls'",
            "env rm -rf /",
            "xargs rm",
            "sudo ls",
            "make",
            "cargo test",
            "npm run build",
            "curl example.com",
            "wget example.com",
            "ssh host",
            "find . -exec rm {} ;",
        ):
            self.assertRefused(command)

    def test_a_reader_flag_that_writes_is_refused(self):
        self.assertRefused("tail -f log.txt", "not read-only")
        self.assertRefused("sort -o out.txt in.txt", "not read-only")
        self.assertRefused("tree -o out.txt", "not read-only")

    def test_a_reader_flag_that_executes_is_refused(self):
        self.assertRefused("rg --pre 'rm -rf /' pattern .", "not read-only")
        self.assertRefused("rg -z pattern archive.zip", "not read-only")
        self.assertRefused("find . -delete", "allowlist")
        self.assertRefused("find . -fprint out.txt", "allowlist")
        self.assertRefused("find . -execdir rm {} ;", "operator")


class TestGit(ProbeTestCase):
    def test_read_only_subcommands_are_allowed(self):
        for command in ("git log", "git diff", "git show", "git status", "git grep x"):
            self.assertAllowed(command)

    def test_a_global_flag_with_a_value_does_not_hide_the_subcommand(self):
        """`git -C <dir> log` is how a probe reaches a repo from another directory.

        The path after `-C` is a value, not the sub-command: reading it as one refuses
        the most common probe there is.
        """
        for command in ("git -C /tmp log", "git -C /tmp log --oneline -3",
                        "git --git-dir /tmp/x log", "git --work-tree /tmp log"):
            self.assertAllowed(command)
        self.assertRefused("git -C", "sub-command")

    def test_mutating_subcommands_are_refused(self):
        for command in (
            "git add .",
            "git commit -m x",
            "git push",
            "git pull",
            "git fetch",
            "git checkout main",
            "git switch main",
            "git reset --hard",
            "git clean -fd",
            "git rm file",
            "git mv a b",
            "git apply patch.diff",
            "git gc",
            "git config user.name x",
            "git filter-branch",
            "git update-index --add x",
            "git checkout-index -a",
        ):
            self.assertRefused(command, "not a read-only sub-command")

    def test_global_flags_that_inject_config_or_a_pager_are_refused(self):
        for command in (
            "git -c alias.l='!rm -rf /' l",
            "git --config-env=x=y status",
            "git --exec-path=/tmp status",
            "git --paginate log",
        ):
            self.assertRefused(command, "not allowed")

    def test_subcommand_flags_that_write_or_execute_are_refused(self):
        for command in (
            "git log --output=o.txt",
            "git diff --output=o.txt",
            "git show --ext-diff",
            "git log --textconv",
            "git grep -O rm pattern",
        ):
            self.assertRefused(command, "not read-only")

    def test_listing_subcommands_need_their_listing_tier(self):
        """A sub-command that mutates unless asked to list is refused outside its tier.

        `git branch new-thing`, `git stash push` and `git reflog expire` are all refused
        for this reason, which is a different message from "not a read-only sub-command".
        """
        for command in ("git branch -l", "git tag -l", "git stash list", "git worktree list"):
            self.assertAllowed(command)
        for command in (
            "git branch new-branch",
            "git tag v1.0",
            "git stash",
            "git stash push",
            "git reflog expire --all",
            "git worktree add ../x",
            "git submodule update --init",
            "git notes add -m x",
        ):
            self.assertRefused(command, "listing")
        for command in ("git branch -l v1", "git stash list extra"):
            self.assertRefused(command, "no positional")


class TestProcessShape(ProbeTestCase):
    def test_process_arguments_are_refused(self):
        for key, value in (
            ("background", True),
            ("pty", True),
            ("notify", True),
            ("heartbeat", 60),
            ("persist_on_release", True),
        ):
            self.assertRefused("git log", key, **{key: value})

    def test_a_non_mapping_is_refused(self):
        for args in (None, ["git", "log"], "git log", 7):
            self.assertIsNotNone(probe.probe_refusal(args), args)

    def test_a_missing_or_empty_command_is_refused(self):
        self.assertIsNotNone(probe.probe_refusal({}))
        self.assertIsNotNone(probe.probe_refusal({"command": ""}))
        self.assertIsNotNone(probe.probe_refusal({"command": "   "}))
        self.assertIsNotNone(probe.probe_refusal({"command": ["git", "log"]}))


if __name__ == "__main__":
    unittest.main()
