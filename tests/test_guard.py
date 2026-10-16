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

#: Tools that must stay blocked in plan mode: they execute, mutate, or leave the machine.
NEVER_IN_PLAN = ("terminal", "patch", "skill_manage", "delegate_task", "memory", "write_file")

#: A path that names a plans directory, for probing tools other than write_file.
PLAN_PATH_ARGS = {"path": ".hermes/plans/x.md", "command": "ls -la .hermes/plans", "content": "x"}


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
        state.set_mode("writable", source="test")
        for tool in sorted(plugin.READ_ONLY_TOOLS | set(NEVER_IN_PLAN) | {"computer_use"}):
            self.assertIsNone(self.block(tool), tool)


class TestReadonly(GuardTestCase):
    def test_readonly_allows_every_allowlisted_tool(self):
        state.set_mode("readonly", source="test")
        for tool in sorted(plugin.READ_ONLY_TOOLS):
            self.assertIsNone(self.block(tool), tool)

    def test_readonly_blocks_a_shell_command(self):
        state.set_mode("readonly", source="test")
        result = self.block("terminal", {"command": "rm -rf /"})
        self.assertEqual(result["action"], "block")
        self.assertIn("read-only mode", result["message"])

    def test_readonly_blocks_the_plan_file_too(self):
        state.set_mode("readonly", source="test")
        result = self.block("write_file", {"path": ".hermes/plans/x.md", "content": "x"})
        self.assertEqual(result["action"], "block")


class TestPlan(GuardTestCase):
    def test_plan_allows_every_allowlisted_tool(self):
        state.set_mode("plan", source="test")
        for tool in sorted(plugin.READ_ONLY_TOOLS):
            self.assertIsNone(self.block(tool), tool)

    def test_plan_blocks_execution_and_edits(self):
        state.set_mode("plan", source="test")
        for tool in NEVER_IN_PLAN:
            result = self.block(tool, {"path": "src/app.py", "command": "ls", "content": "x"})
            self.assertIsNotNone(result, tool)
            self.assertEqual(result["action"], "block", tool)

    def test_plan_block_message_names_the_mode_and_the_way_out(self):
        state.set_mode("plan", source="test")
        message = self.block("terminal", {"command": "ls"})["message"]
        self.assertIn("PLAN mode", message)
        self.assertIn("/readonly writable", message)

    def test_plan_allows_the_plan_markdown_anywhere_under_a_plans_directory(self):
        state.set_mode("plan", source="test")
        for path in (
            ".hermes/plans/2026-10-16_113922-thing.md",
            "./.hermes/plans/thing.md",
            "/home/user/projects/thanatos/hosts/.hermes/plans/thing.md",
            "../../.hermes/plans/deep/nested.md",
        ):
            self.assertIsNone(self.block("write_file", {"path": path, "content": "x"}), path)

    def test_plan_blocks_a_plan_path_that_escapes_the_plans_directory(self):
        """Naming `.hermes/plans` and then leaving it is not a plan file.

        A component test on the raw string accepts these, which would hand plan mode
        an arbitrary `*.md` write anywhere on the machine.
        """
        state.set_mode("plan", source="test")
        for path in (
            ".hermes/plans/../../../evil.md",
            ".hermes/plans/../../../../../../../tmp/owned.md",
            ".hermes/plans/../../.bashrc.md",
            ".hermes/plans/../not-plans/x.md",
        ):
            result = self.block("write_file", {"path": path, "content": "x"})
            self.assertIsNotNone(result, path)
            self.assertEqual(result["action"], "block", path)

    def test_plan_allows_a_plan_file_reached_through_a_symlinked_plans_directory(self):
        """`resolve()` follows symlinks, so a symlinked `.hermes` hides the pair.

        The raw components still name a plans directory and climb nowhere (`..` is
        absent), so the write is allowed, and it lands inside whatever the user's own
        symlink points at — which is what that symlink means.
        """
        state.set_mode("plan", source="test")
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

    def test_plan_blocks_the_carve_out_for_every_tool_except_write_file(self):
        """The carve-out is scoped to write_file.

        Without that scope, `patch` — and worse, `terminal` — would be allowed
        whenever the call happens to carry a plans path, which the block messages
        themselves say is not allowed.
        """
        state.set_mode("plan", source="test")
        for tool in ("patch", "terminal", "skill_manage", "delegate_task", "read_file"):
            if tool in plugin.READ_ONLY_TOOLS:
                continue  # allowed by the allowlist, not by the carve-out
            result = self.block(tool, dict(PLAN_PATH_ARGS))
            self.assertIsNotNone(result, tool)
            self.assertEqual(result["action"], "block", tool)

    def test_plan_blocks_a_path_that_cannot_be_expanded_instead_of_raising(self):
        """`~<unknown-user>/...` makes `Path.expanduser()` raise.

        A raising pre_tool_call still fails closed, but with a policy-error message
        instead of the plan block — and the file it points at is not a plan file.
        """
        state.set_mode("plan", source="test")
        result = self.block(
            "write_file", {"path": "~nosuchuser-9f3a1c/.hermes/plans/x.md", "content": "x"}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "block")
        self.assertIn("PLAN mode", result["message"])

    def test_plan_blocks_writes_that_are_not_plan_markdown(self):
        state.set_mode("plan", source="test")
        for path in ("src/app.py", ".hermes/plans/thing.txt", ".hermes/plan/thing.md",
                     ".hermesnotes.md", ".hermes/plans", ""):
            result = self.block("write_file", {"path": path, "content": "x"})
            self.assertIsNotNone(result, path)
            self.assertEqual(result["action"], "block", path)

    def test_plan_blocks_a_write_with_no_usable_path(self):
        state.set_mode("plan", source="test")
        for args in ({}, {"path": None}, {"path": 5}, {"path": ["a.md"]}):
            result = self.block("write_file", args)
            self.assertIsNotNone(result, args)
            self.assertEqual(result["action"], "block", args)


class TestLiveSwitch(GuardTestCase):
    def test_the_guard_re_reads_the_mode_on_every_call(self):
        """A mode flipped mid-turn (chip, or /readonly) applies to the NEXT tool call."""
        state.set_mode("plan", source="test")
        self.assertEqual(self.block("terminal")["action"], "block")
        state.set_mode("writable", source="test")
        self.assertIsNone(self.block("terminal"))

    def test_the_guard_callback_accepts_forward_compatible_kwargs(self):
        self.assertTrue(accepts_var_kwargs(plugin.guard))


if __name__ == "__main__":
    unittest.main()
