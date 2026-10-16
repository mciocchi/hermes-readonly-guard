"""register(): the plugin's contract with the runtime.

The hook names and the command's argument surface are load-bearing — a wrong hook
name means the guard never fires, and the command is the only way a user flips a
mode — so they get their own tests rather than riding on the guard's.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from plugin_under_test import accepts_var_kwargs, load_plugin, load_state

plugin = load_plugin()
state = load_state()


class FakeContext:
    """Minimal stand-in for PluginContext: records whatever register() wires up."""

    def __init__(self):
        self.hooks = {}
        self.commands = {}

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


class TestCommandSurface(RegistrationTestCase):
    def test_the_command_advertises_every_argument_it_accepts(self):
        advertised = self.ctx.commands["readonly"]["args_hint"]
        for arg in ("status", "readonly", "plan", "writable", "on", "off", "toggle"):
            self.assertIn(arg, advertised, arg)

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
            self.assertEqual(state.read_mode(), arg, arg)

    def test_on_and_off_stay_aliases_for_readonly_and_writable(self):
        self.run_command("on")
        self.assertEqual(state.read_mode(), state.MODE_READONLY)
        self.run_command("off")
        self.assertEqual(state.read_mode(), state.MODE_WRITABLE)

    def test_toggle_cycles_through_all_three_modes_and_names_the_one_it_landed_on(self):
        seen = []
        for _ in range(4):
            out = self.run_command("toggle")
            seen.append(state.read_mode())
            # The 1.x message claimed "OFF (writes allowed)" whenever the result was
            # not readonly, which was false for plan mode. The message must name the mode.
            self.assertIn(state.read_mode(), out)
        self.assertEqual(seen, ["plan", "writable", "readonly", "plan"])

    def test_an_unknown_argument_is_reported_and_changes_nothing(self):
        self.run_command("plan")
        out = self.run_command("bogus")
        self.assertIn("bogus", out)
        self.assertEqual(state.read_mode(), state.MODE_PLAN)


if __name__ == "__main__":
    unittest.main()
