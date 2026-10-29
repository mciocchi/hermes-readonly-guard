"""pre_tool_call guard: what each mode lets through."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from plugin_under_test import accepts_var_kwargs, load_plugin, load_state

plugin = load_plugin()
state = load_state()

#: The per-session model: every test in this module drives ONE session, and the process
#: binding is what `resolve_mode` falls back to for a call that carries no session_id
#: (a slash command, or a subagent's call). `set_mode` is the old global switch's
#: spelling, now scoped to that session.
TEST_SESSION = "s-under-test"
# Hard set, not setdefault: the harness that runs the suite exports its own
# HERMES_SESSION_ID, and inheriting it would test the wrong session.
os.environ["HERMES_SESSION_ID"] = TEST_SESSION


def set_mode(mode, source="test"):
    """Set the mode this module's session runs under."""
    return state.set_session_mode(TEST_SESSION, mode, source=source)

#: Tools that must stay blocked in plan mode: they execute, mutate, or leave the machine.
NEVER_IN_PLAN = ("terminal", "patch", "skill_manage", "delegate_task", "memory", "write_file")

#: A path that names a plans directory, for probing tools other than write_file.
PLAN_PATH_ARGS = {"path": ".hermes/plans/x.md", "command": "ls -la .hermes/plans", "content": "x"}


def symlinks_are_allowed() -> bool:
    """True when this host can create a directory symlink.

    Windows needs Developer Mode or admin, and a CI runner has neither, so the capability
    is asked for rather than assumed from ``sys.platform``: a Windows box with Developer
    Mode still exercises these tests, and a locked-down one skips them with a reason.
    """
    with tempfile.TemporaryDirectory() as tmp:
        target, link = Path(tmp) / "target", Path(tmp) / "link"
        target.mkdir()
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


#: Applied to the three tests that need a symlink to exist at all.
NEEDS_SYMLINKS = unittest.skipUnless(
    symlinks_are_allowed(), "this host cannot create symlinks (Windows without Developer Mode)"
)


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"HERMES_HOME": tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def block(self, tool, args=None):
        """The guard's decision for one tool call."""
        return plugin.guard(tool, args or {}, task_id="t")


class TestWritable(GuardTestCase):
    def test_writable_blocks_nothing(self):
        set_mode("writable", source="test")
        for tool in sorted(plugin.READ_ONLY_TOOLS | set(NEVER_IN_PLAN) | {"computer_use"}):
            self.assertIsNone(self.block(tool), tool)


class TestReadonly(GuardTestCase):
    def test_readonly_allows_every_allowlisted_tool(self):
        set_mode("readonly", source="test")
        for tool in sorted(plugin.READ_ONLY_TOOLS):
            self.assertIsNone(self.block(tool), tool)

    def test_readonly_blocks_a_shell_command(self):
        set_mode("readonly", source="test")
        result = self.block("terminal", {"command": "rm -rf /"})
        self.assertEqual(result["action"], "block")
        self.assertIn("read-only mode", result["message"])

    def test_readonly_blocks_the_plan_file_too(self):
        set_mode("readonly", source="test")
        result = self.block("write_file", {"path": ".hermes/plans/x.md", "content": "x"})
        self.assertEqual(result["action"], "block")


class TestReadonlyProbes(GuardTestCase):
    """Read-only admits the same single commands as plan — and nothing more."""

    def test_readonly_allows_a_single_read_only_command(self):
        set_mode("readonly", source="test")
        for command in ("ls -la", "git status --porcelain", "git log --oneline -3",
                        "wc -l README.md", "rg -n TODO tests"):
            self.assertIsNone(self.block("terminal", {"command": command}), command)

    def test_readonly_refuses_composition_writes_and_unknown_programs(self):
        set_mode("readonly", source="test")
        for command in ("ls; rm -rf build", "ls && rm -rf build", "ls > out.txt",
                        "cat < /etc/passwd", "rm -rf build", "sudo ls",
                        "git commit -m x", "git log --output=log.txt"):
            result = self.block("terminal", {"command": command})
            self.assertIsNotNone(result, command)
            self.assertEqual(result["action"], "block", command)
            self.assertIn("read-only mode", result["message"], command)

    def test_readonly_refusal_gives_the_specific_reason(self):
        set_mode("readonly", source="test")
        message = self.block("terminal", {"command": "git commit -m x"})["message"]
        self.assertIn("Refused:", message)
        self.assertIn("terminal", message)          # the message names what it DOES allow

    def test_readonly_still_blocks_plan_files_code_and_delegation(self):
        set_mode("readonly", source="test")
        for tool, args in (
            ("write_file", {"path": ".hermes/plans/x.md", "content": "x"}),
            ("patch", {"path": ".hermes/plans/x.md", "old_string": "a", "new_string": "b"}),
            ("execute_code", {"code": "print(1)"}),
            ("delegate_task", {"goal": "x"}),
            ("terminal", {"command": "ls", "background": True}),
        ):
            result = self.block(tool, args)
            self.assertIsNotNone(result, (tool, args))
            self.assertEqual(result["action"], "block", (tool, args))


class TestModeOrdering(GuardTestCase):
    """readonly says nothing plan allows, and plan says nothing writable refuses.

    Stated as one property so a later change cannot quietly make the stricter mode
    admit more than the looser one — which is the shape of bug the plan-markdown
    carve-out could have been.
    """

    CALLS = (
        [("terminal", {"command": command}) for command in
         ("ls", "git status", "ls; id", "rm -rf build", "git log --output=x.txt")]
        + [(tool, {"path": ".hermes/plans/x.md", "command": "ls", "content": "x"})
           for tool in sorted(plugin.READ_ONLY_TOOLS | set(NEVER_IN_PLAN) | {"execute_code"})]
    )

    def test_readonly_admits_nothing_that_plan_refuses(self):
        for tool, args in self.CALLS:
            if plugin._is_plan_edit(tool, args):
                continue  # the one documented difference; the next test pins it
            set_mode("plan", source="test")
            plan_verdict = self.block(tool, args)
            set_mode("readonly", source="test")
            readonly_verdict = self.block(tool, args)
            if plan_verdict is None:
                self.assertIsNone(readonly_verdict, f"readonly refused what plan allows: {tool} {args}")

    def test_the_plan_markdown_is_the_only_thing_readonly_refuses(self):
        """readonly == plan minus the plan file. If a second difference appears, this fails."""
        self.assertTrue(plugin._is_plan_edit("write_file", {"path": ".hermes/plans/x.md"}))
        set_mode("plan", source="test")
        self.assertIsNone(self.block("write_file", {"path": ".hermes/plans/x.md", "content": "x"}))
        set_mode("readonly", source="test")
        self.assertIsNotNone(self.block("write_file", {"path": ".hermes/plans/x.md", "content": "x"}))

    def test_writable_refuses_nothing(self):
        set_mode("writable", source="test")
        for tool, args in self.CALLS:
            self.assertIsNone(self.block(tool, args), (tool, args))


class TestPlan(GuardTestCase):
    def test_plan_allows_every_allowlisted_tool(self):
        set_mode("plan", source="test")
        for tool in sorted(plugin.READ_ONLY_TOOLS):
            self.assertIsNone(self.block(tool), tool)

    def test_plan_blocks_execution_and_edits(self):
        set_mode("plan", source="test")
        for tool in NEVER_IN_PLAN:
            result = self.block(tool, {"path": "src/app.py", "command": "ls", "content": "x"})
            self.assertIsNotNone(result, tool)
            self.assertEqual(result["action"], "block", tool)

    def test_plan_block_message_names_the_mode_and_the_way_out(self):
        set_mode("plan", source="test")
        # A refused command, not an allowed probe: `ls` runs in plan mode now, so it
        # would come back as None and there would be no message to inspect.
        message = self.block("terminal", {"command": "rm -rf /tmp/x"})["message"]
        self.assertIn("PLAN mode", message)
        self.assertIn("/readonly writable", message)

    def test_plan_allows_the_plan_markdown_anywhere_under_a_plans_directory(self):
        set_mode("plan", source="test")
        for path in (
            ".hermes/plans/2026-10-16_113922-thing.md",
            "./.hermes/plans/thing.md",
            "/srv/work/.hermes/plans/thing.md",
            "../../.hermes/plans/deep/nested.md",
        ):
            self.assertIsNone(self.block("write_file", {"path": path, "content": "x"}), path)

    def test_plan_blocks_a_plan_path_that_escapes_the_plans_directory(self):
        """Naming `.hermes/plans` and then leaving it is not a plan file.

        A component test on the raw string accepts these, which would hand plan mode
        an arbitrary `*.md` write anywhere on the machine.
        """
        set_mode("plan", source="test")
        for path in (
            ".hermes/plans/../../../evil.md",
            ".hermes/plans/../../../../../../../tmp/owned.md",
            ".hermes/plans/../../.bashrc.md",
            ".hermes/plans/../not-plans/x.md",
        ):
            result = self.block("write_file", {"path": path, "content": "x"})
            self.assertIsNotNone(result, path)
            self.assertEqual(result["action"], "block", path)

    @NEEDS_SYMLINKS
    def test_plan_allows_a_plan_file_reached_through_a_symlinked_plans_directory(self):
        """A symlinked `.hermes` is the user naming the plans directory by another route.

        The file resolves *inside* the resolved plans directory, which is the whole
        test: the name points at the directory, so the write lands in it.
        """
        set_mode("plan", source="test")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            work = Path(tmp) / "work"
            (target / "plans").mkdir(parents=True)
            work.mkdir()
            (work / ".hermes").symlink_to(target, target_is_directory=True)
            original = Path.cwd()
            try:
                os.chdir(work)
                self.assertIsNone(
                    self.block("write_file", {"path": ".hermes/plans/x.md", "content": "x"})
                )
            finally:
                os.chdir(original)

    @NEEDS_SYMLINKS
    def test_plan_blocks_a_plan_path_that_leaves_through_a_symlink_inside_plans(self):
        """A link *inside* `.hermes/plans` points out of the tree, so the write is not a plan.

        The raw components alone trust this link — only the resolved path shows that
        the file lands outside the plans directory.
        """
        set_mode("plan", source="test")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            outside = Path(tmp) / "outside"
            (work / ".hermes" / "plans").mkdir(parents=True)
            outside.mkdir()
            (work / ".hermes" / "plans" / "escape").symlink_to(outside, target_is_directory=True)
            original = Path.cwd()
            try:
                os.chdir(work)
                for path in (".hermes/plans/escape/x.md", ".hermes/plans/escape/deep/x.md"):
                    result = self.block("write_file", {"path": path, "content": "x"})
                    self.assertIsNotNone(result, path)
                    self.assertEqual(result["action"], "block", path)
            finally:
                os.chdir(original)

    @NEEDS_SYMLINKS
    def test_plan_blocks_a_plan_path_whose_leaf_is_a_symlink(self):
        """Writing through a symlinked leaf lands the content wherever the link points."""
        set_mode("plan", source="test")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            outside = Path(tmp) / "outside.md"
            (work / ".hermes" / "plans").mkdir(parents=True)
            outside.write_text("not a plan\n", encoding="utf-8")
            (work / ".hermes" / "plans" / "plan.md").symlink_to(outside)
            original = Path.cwd()
            try:
                os.chdir(work)
                result = self.block("write_file", {"path": ".hermes/plans/plan.md", "content": "x"})
                self.assertIsNotNone(result)
                self.assertEqual(result["action"], "block")
            finally:
                os.chdir(original)

    def test_plan_blocks_the_carve_out_for_every_tool_except_the_plan_editors(self):
        """The carve-out is scoped to the two tools that write a plan file.

        Without that scope, `terminal` — and anything else — would be allowed whenever
        the call happens to carry a plans path, which the block messages say it is not.
        """
        set_mode("plan", source="test")
        for tool in ("terminal", "skill_manage", "delegate_task", "read_file"):
            if tool in plugin.READ_ONLY_TOOLS:
                continue  # allowed by the allowlist, not by the carve-out
            result = self.block(tool, dict(PLAN_PATH_ARGS))
            self.assertIsNotNone(result, tool)
            self.assertEqual(result["action"], "block", tool)

    def test_plan_blocks_a_path_that_cannot_be_expanded_instead_of_raising(self):
        """`~<unknown-user>/...` makes `Path.expanduser()` raise — on POSIX.

        A raising pre_tool_call still fails closed, but with a policy-error message
        instead of the plan block. ``ntpath.expanduser`` leaves an unknown ``~user``
        alone instead of raising, so on Windows there is no exception to guard against
        and the path is just a plans directory under the cwd — nothing to assert here.
        """
        try:
            Path("~nosuchuser-9f3a1c").expanduser()
        except (RuntimeError, KeyError):
            pass
        else:
            self.skipTest("this host's expanduser leaves an unknown ~user alone; nothing raises")
        set_mode("plan", source="test")
        result = self.block(
            "write_file", {"path": "~nosuchuser-9f3a1c/.hermes/plans/x.md", "content": "x"}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "block")
        self.assertIn("PLAN mode", result["message"])

    def test_plan_blocks_writes_that_are_not_plan_markdown(self):
        set_mode("plan", source="test")
        for path in ("src/app.py", ".hermes/plans/thing.txt", ".hermes/plan/thing.md",
                     ".hermesnotes.md", ".hermes/plans", ""):
            result = self.block("write_file", {"path": path, "content": "x"})
            self.assertIsNotNone(result, path)
            self.assertEqual(result["action"], "block", path)

    def test_plan_blocks_a_write_with_no_usable_path(self):
        set_mode("plan", source="test")
        for args in ({}, {"path": None}, {"path": 5}, {"path": ["a.md"]}):
            result = self.block("write_file", args)
            self.assertIsNotNone(result, args)
            self.assertEqual(result["action"], "block", args)

    def test_plan_blocks_a_write_whose_args_are_not_a_mapping(self):
        """`args` is whatever the call carried; a non-dict must block, not raise.

        A raising pre_tool_call fails closed, but with a policy-error message instead
        of the plan block, and the guard's own message is part of what the user reads.
        """
        set_mode("plan", source="test")
        for args in (["x"], "a string", 7, 3.5, b"bytes"):
            result = plugin.guard("write_file", args, task_id="t")
            self.assertIsNotNone(result, args)
            self.assertEqual(result["action"], "block", args)
            self.assertIn("PLAN mode", result["message"])


class TestLiveSwitch(GuardTestCase):
    def test_the_guard_re_reads_the_mode_on_every_call(self):
        """A mode flipped mid-turn (chip, or /readonly) applies to the NEXT tool call."""
        set_mode("plan", source="test")
        self.assertEqual(self.block("terminal")["action"], "block")
        set_mode("writable", source="test")
        self.assertIsNone(self.block("terminal"))

    def test_the_guard_callback_accepts_forward_compatible_kwargs(self):
        self.assertTrue(accepts_var_kwargs(plugin.guard))


class TestPlanProbes(GuardTestCase):
    """Both restricting modes may read the repo through `terminal`, on the same allowlist."""

    def test_plan_allows_a_probe_command(self):
        set_mode("plan", source="test")
        for command in ("git log --oneline -5", "ls", "rg 'def guard' .", "find . -name '*.py'"):
            self.assertIsNone(self.block("terminal", {"command": command}), command)

    def test_readonly_allows_the_same_probe(self):
        set_mode("readonly", source="test")
        self.assertIsNone(self.block("terminal", {"command": "git log --oneline -5"}))

    def test_readonly_blocks_a_probe_that_is_not_read_only(self):
        set_mode("readonly", source="test")
        for command in ("rm -rf /tmp/x", "git commit -m x", "git log; rm -rf /",
                        "git log > out.txt", "find . -delete"):
            result = self.block("terminal", {"command": command})
            self.assertIsNotNone(result, command)
            self.assertEqual(result["action"], "block", command)

    def test_plan_blocks_a_probe_that_is_not_read_only(self):
        set_mode("plan", source="test")
        for command in ("rm -rf /tmp/x", "git commit -m x", "git log; rm -rf /",
                        "git log > out.txt", "find . -delete"):
            result = self.block("terminal", {"command": command})
            self.assertIsNotNone(result, command)
            self.assertEqual(result["action"], "block", command)

    def test_plan_blocks_a_background_probe(self):
        set_mode("plan", source="test")
        result = self.block("terminal", {"command": "git log", "background": True})
        self.assertEqual(result["action"], "block")
        self.assertIn("background", result["message"])

    def test_the_plan_block_message_names_the_refusal(self):
        set_mode("plan", source="test")
        message = self.block("terminal", {"command": "rm -rf /tmp/x"})["message"]
        self.assertIn("PLAN mode", message)
        self.assertIn("Refused:", message)
        self.assertIn("terminal", message)


class TestPlanEdits(GuardTestCase):
    """Plan mode may write *and patch* a plan file: superseding a plan is an edit."""

    PLAN = ".hermes/plans/2026-10-26_215732-existing.md"

    def test_plan_allows_a_patch_to_a_plan_file(self):
        set_mode("plan", source="test")
        args = {"path": self.PLAN, "old_string": "## Old", "new_string": "## New"}
        self.assertIsNone(self.block("patch", args))

    def test_plan_blocks_a_patch_to_a_non_plan_file(self):
        set_mode("plan", source="test")
        result = self.block("patch", {"path": "src/app.py", "old_string": "a", "new_string": "b"})
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "block")

    def test_readonly_blocks_a_patch_to_a_plan_file(self):
        set_mode("readonly", source="test")
        result = self.block("patch", {"path": self.PLAN, "old_string": "a", "new_string": "b"})
        self.assertEqual(result["action"], "block")
        self.assertIn("read-only mode", result["message"])

    def test_plan_blocks_a_v4a_patch_even_when_it_names_a_plan_file(self):
        """V4A carries several file headers, so a `path` naming a plan proves nothing.

        The patch handler accepts this shape from any model, advertised or not.
        """
        set_mode("plan", source="test")
        args = {
            "mode": "patch",
            "path": self.PLAN,
            "patch": "*** Begin Patch\n*** Update File: src/app.py\n@@\n-x\n+y\n*** End Patch",
        }
        result = self.block("patch", args)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "block")

    def test_plan_blocks_a_v4a_patch_without_a_path(self):
        set_mode("plan", source="test")
        args = {"mode": "patch", "patch": "*** Begin Patch\n*** Update File: x.md\n*** End Patch"}
        self.assertEqual(self.block("patch", args)["action"], "block")

    def test_plan_blocks_a_patch_that_escapes_the_plans_directory(self):
        set_mode("plan", source="test")
        for path in (".hermes/plans/../../../evil.md", ".hermes/plans/../../.bashrc.md"):
            args = {"path": path, "old_string": "a", "new_string": "b"}
            self.assertEqual(self.block("patch", args)["action"], "block", path)


class TestPerSessionModes(GuardTestCase):
    """One session's mode must never decide another session's tool calls."""

    def set_default(self, mode):
        self.addCleanup(plugin.settings.set_reader, None)
        plugin.settings.set_reader(lambda key, default: mode)

    def block_for(self, session_id, tool="terminal", args=None):
        # A non-probe command on purpose: these tests are about WHICH session decides,
        # not about probe policy, so the fixture must be one every restricting mode
        # refuses regardless of how the probe table evolves.
        return plugin.guard(tool, args or {"command": "rm -rf build"}, task_id="t", session_id=session_id)

    def test_a_writable_session_does_not_unblock_a_readonly_session(self):
        self.set_default("readonly")
        state.set_session_mode("s-writable", "writable", source="test")
        self.assertIsNone(self.block_for("s-writable"))
        result = self.block_for("s-readonly")
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "block")
        self.assertIn("read-only mode", result["message"])

    def test_each_session_reads_its_own_mode(self):
        self.set_default("readonly")
        state.set_session_mode("s-plan", "plan", source="test")
        state.set_session_mode("s-writable", "writable", source="test")
        self.assertIsNone(self.block_for("s-plan", "terminal", {"command": "ls"}))
        # plan admits a probe, not a write; writable admits both
        self.assertIsNotNone(self.block_for("s-plan", "write_file", {"path": "src/app.py", "content": "x"}))
        self.assertIsNone(self.block_for("s-writable", "write_file", {"path": "src/app.py", "content": "x"}))

    def test_an_unknown_session_uses_the_configured_default(self):
        self.set_default("writable")
        self.assertIsNone(self.block_for("never-seen"))
        self.set_default("readonly")
        self.assertIsNotNone(self.block_for("never-seen"))

    def test_a_subagent_inherits_the_spawning_session_mode(self):
        """A subagent's tool call carries the CHILD's session id; the session vars still
        name the parent, so the child runs under the parent's mode."""
        self.set_default("readonly")
        state.set_session_mode("parent", "writable", source="test")
        with mock.patch.dict(os.environ, {"HERMES_SESSION_ID": "parent"}):
            self.assertIsNone(self.block_for("subagent-1-abc"))

    def test_a_subagent_with_no_known_parent_gets_the_default(self):
        self.set_default("readonly")
        with mock.patch.dict(os.environ, {"HERMES_SESSION_ID": "unknown-parent"}):
            self.assertIsNotNone(self.block_for("subagent-2-def"))

    def test_the_block_message_says_the_switch_is_this_session(self):
        self.set_default("readonly")
        message = plugin.guard("terminal", {"command": "rm -rf build"}, task_id="t", session_id="s")["message"]
        self.assertIn("this session", message)


class TestWritableClock(GuardTestCase):
    """Turn start renews or lapses; the guard never cuts the turn that renewed it."""

    def setUp(self):
        super().setUp()
        self.addCleanup(plugin.settings.set_reader, None)
        plugin.settings.set_reader(
            lambda key, default: 30 if key == plugin.settings.EXPIRY_SETTING else default
        )

    def turn(self, task_id="task-1"):
        return plugin.turn_start(user_message="go", session_id=TEST_SESSION, task_id=task_id)

    def block_as(self, task_id, path="a"):
        return plugin.guard("write_file", {"path": path, "content": "x"}, task_id=task_id)

    def age(self, minutes):
        table = state._sessions()
        table[TEST_SESSION]["renewed_at"] = state.time.time() - minutes * 60
        state._write({"version": state.SCHEMA_VERSION, "sessions": table})

    def test_a_turn_renews_the_clock(self):
        set_mode("writable", source="test")
        self.turn("task-1")
        self.assertEqual(state._sessions()[TEST_SESSION]["renewed_turn"], "task-1")

    def test_silence_past_the_ttl_latches_readonly(self):
        set_mode("writable", source="test")
        self.turn("task-1")
        self.age(31)
        self.turn("task-2")
        self.assertEqual(state.get_session_mode(TEST_SESSION), "readonly")

    def test_the_turn_that_renewed_it_keeps_running(self):
        set_mode("writable", source="test")
        self.turn("task-1")
        self.age(90)
        self.assertIsNone(self.block_as("task-1"))

    def test_a_lapsed_grant_does_not_revive_on_the_next_message(self):
        set_mode("writable", source="test")
        self.turn("task-1")
        self.age(31)
        self.turn("task-2")                      # the user speaks again
        self.assertIsNotNone(self.block_as("task-2"))

    def test_zero_disables_the_clock(self):
        plugin.settings.set_reader(
            lambda key, default: 0 if key == plugin.settings.EXPIRY_SETTING else default
        )
        set_mode("writable", source="test")
        self.turn("task-1")
        self.age(10_000)
        self.assertIsNone(self.block_as("task-1"))


if __name__ == "__main__":
    unittest.main()
