"""register(): the plugin's contract with the runtime.

The hook names and the command's argument surface are load-bearing — a wrong hook
name means the guard never fires, and the command is the only way a user flips a
mode — so they get their own tests rather than riding on the guard's. The manifest
is checked here too: it is the runtime's declaration, and drift from `register()`
is otherwise visible only when someone remembers to run `hermes plugins doctor`.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from unittest import mock

from plugin_under_test import PLUGIN_DIR, accepts_var_kwargs, load_plugin, load_state

plugin = load_plugin()
state = load_state()

#: The session these command tests run as. Hard set: the harness that runs the suite
#: exports its own HERMES_SESSION_ID, and inheriting it would test the wrong session.
TEST_SESSION = "s-under-test"
os.environ["HERMES_SESSION_ID"] = TEST_SESSION

#: Every argument the command accepts, for the bidirectional hint check.
COMMAND_ARGUMENTS = {"status", "readonly", "plan", "writable", "on", "off", "toggle"}


class FakeContext:
    """Minimal stand-in for PluginContext: records whatever register() wires up."""

    def __init__(self):
        self.hooks = {}
        self.commands = {}
        self.settings = {}   # stand-in for plugins.entries.<id>.settings

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, hook_name, callback):
        self.hooks[hook_name] = callback

    def register_command(self, name, handler=None, description="", args_hint=""):
        self.commands[name] = {"handler": handler, "description": description, "args_hint": args_hint}


class RegistrationTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"HERMES_HOME": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.ctx = FakeContext()
        plugin.register(self.ctx)
        # A fresh HERMES_HOME has no state file, so the session starts in readonly.
        self.run_command = self.ctx.commands["readonly"]["handler"]


class TestRegisteredHooks(RegistrationTestCase):
    def test_the_policy_and_plan_hooks_are_registered_under_their_real_names(self):
        self.assertEqual(set(self.ctx.hooks), {"pre_tool_call", "pre_llm_call"})

    def test_each_hook_name_carries_the_callback_that_belongs_to_it(self):
        self.assertIs(self.ctx.hooks["pre_tool_call"], plugin.guard)
        self.assertIs(self.ctx.hooks["pre_llm_call"], plugin.plan_directive)

    def test_every_hook_accepts_forward_compatible_kwargs(self):
        # `hermes plugins doctor` rejects a hook callback whose signature omits **kwargs.
        for name, callback in self.ctx.hooks.items():
            self.assertTrue(accepts_var_kwargs(callback), name)


class TestManifestMatchesRegistration(RegistrationTestCase):
    """plugin.yaml is what the runtime reads; register() is what it gets."""

    @staticmethod
    def declared(section: str) -> set[str]:
        """One list section of plugin.yaml, read without a YAML dependency."""
        lines = (PLUGIN_DIR / "plugin.yaml").read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(f"{section}:"))
        names = set()
        for line in lines[start + 1:]:
            if not line.startswith("  - "):
                break
            names.add(line[len("  - "):].strip())
        return names

    def test_provides_hooks_declares_exactly_the_hooks_that_are_registered(self):
        self.assertEqual(self.declared("provides_hooks"), set(self.ctx.hooks))

    def test_provides_tools_declares_nothing_because_no_tool_is_registered(self):
        self.assertEqual(self.declared("provides_tools"), set())


class TestCommandSurface(RegistrationTestCase):
    def test_the_command_advertises_exactly_the_arguments_it_accepts(self):
        """Bidirectional: a hint that drops a token, or invents one, fails here."""
        advertised = set(re.findall(r"[a-z]+", self.ctx.commands["readonly"]["args_hint"]))
        self.assertEqual(advertised, COMMAND_ARGUMENTS)

    def test_the_command_is_still_called_readonly(self):
        self.assertEqual(set(self.ctx.commands), {"readonly"})


class TestCommandBehaviour(RegistrationTestCase):
    def test_status_reports_the_mode_and_the_cast_of_modes(self):
        out = self.run_command("status")
        self.assertIn("readonly", out)
        self.assertIn("readonly, plan, writable", out)

    def test_each_mode_argument_selects_that_mode(self):
        for arg in ("readonly", "plan", "writable"):
            self.run_command(arg)
            self.assertEqual(state.get_session_mode(TEST_SESSION), arg, arg)

    def test_on_and_off_stay_aliases_for_readonly_and_writable(self):
        self.run_command("on")
        self.assertEqual(state.get_session_mode(TEST_SESSION), state.MODE_READONLY)
        self.run_command("off")
        self.assertEqual(state.get_session_mode(TEST_SESSION), state.MODE_WRITABLE)

    def test_toggle_cycles_through_all_three_modes_and_names_the_one_it_landed_on(self):
        seen = []
        for _ in range(4):
            out = self.run_command("toggle")
            seen.append(state.get_session_mode(TEST_SESSION))
            # The reply must name the mode it landed on, not a two-state shorthand.
            self.assertIn(state.get_session_mode(TEST_SESSION), out)
        self.assertEqual(seen, ["plan", "writable", "readonly", "plan"])

    def test_an_unknown_argument_is_reported_and_changes_nothing(self):
        self.run_command("plan")
        out = self.run_command("bogus")
        self.assertIn("bogus", out)
        self.assertEqual(state.get_session_mode(TEST_SESSION), state.MODE_PLAN)


class TestReadonlyCommandIsPerSession(unittest.TestCase):
    """/readonly switches the session it is typed in, and nothing else."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(
            os.environ, {"HERMES_HOME": tmp.name, "HERMES_SESSION_ID": "s-cli"}
        )
        env.start()
        self.addCleanup(env.stop)

    def test_readonly_sets_the_current_session_only(self):
        state.set_session_mode("s-other", "writable", source="test")
        plugin._handle_readonly("readonly")
        self.assertEqual(state.get_session_mode("s-cli"), "readonly")
        self.assertEqual(state.get_session_mode("s-other"), "writable")

    def test_readonly_status_names_the_session_the_default_and_the_source(self):
        state.set_session_mode("s-cli", "plan", source="test")
        text = plugin._handle_readonly("status")
        self.assertIn("plan", text)
        self.assertIn("s-cli", text)
        self.assertIn("from session", text)
        self.assertIn("default for new sessions", text)

    def test_readonly_toggle_advances_this_sessions_mode(self):
        state.set_session_mode("s-cli", "plan", source="test")
        plugin._handle_readonly("toggle")
        self.assertEqual(state.get_session_mode("s-cli"), "writable")

    def test_readonly_without_a_session_context_writes_nothing(self):
        os.environ.pop("HERMES_SESSION_ID", None)
        text = plugin._handle_readonly("writable")
        self.assertIn("no session context", text)
        self.assertEqual(state._sessions(), {})


if __name__ == "__main__":
    unittest.main()
