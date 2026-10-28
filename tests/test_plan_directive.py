"""pre_llm_call directive: plan mode sends every turn to the plan skill."""

from __future__ import annotations

import os
import tempfile
import unittest
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

#: The injection always names this, whichever prompt source is available.
SKILL_POINTER = "skill_view(name='plan')"


class PlanDirectiveTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"HERMES_HOME": tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def context(self, user_message="do the thing"):
        result = plugin.plan_directive(user_message=user_message)
        self.assertIsInstance(result, dict)
        return result["context"]


class TestOtherModes(PlanDirectiveTestCase):
    def test_nothing_is_injected_outside_plan_mode(self):
        for mode in ("readonly", "writable"):
            set_mode(mode, source="test")
            self.assertIsNone(plugin.plan_directive(user_message="do the thing"), mode)


class TestPlanMode(PlanDirectiveTestCase):
    def test_the_injection_points_at_the_plan_skill(self):
        set_mode("plan", source="test")
        self.assertIn(SKILL_POINTER, self.context())

    def test_the_injection_reuses_the_built_in_plan_prompt_when_importable(self):
        if plugin.build_plan_prompt is None:
            self.skipTest("agent.plan_prompt not importable — re-run with PYTHONPATH=$REPO")
        set_mode("plan", source="test")
        context = self.context(user_message="add a third mode")
        self.assertIn("[/plan", context)          # Hermes' own /plan banner
        self.assertIn("PLAN MODE", context)
        self.assertIn("add a third mode", context)

    def test_a_multimodal_user_message_does_not_crash_and_still_points_at_the_skill(self):
        set_mode("plan", source="test")
        context = self.context(user_message=[{"type": "text", "text": "hi"}])
        self.assertIn(SKILL_POINTER, context)

    def test_the_callback_accepts_forward_compatible_kwargs(self):
        self.assertTrue(accepts_var_kwargs(plugin.plan_directive))

    def test_the_fallback_context_is_used_when_the_built_in_prompt_is_unavailable(self):
        """The import depends on the interpreter, so the fallback path needs its own test.

        On this machine the Hermes venv has an editable install of `agent`, so the
        import always succeeds and the fallback would otherwise never run anywhere.
        """
        set_mode("plan", source="test")
        with mock.patch.object(plugin, "build_plan_prompt", None):
            context = self.context()
        self.assertIn(SKILL_POINTER, context)
        self.assertIn("PLAN MODE", context)

    def test_a_failing_built_in_prompt_falls_back_instead_of_breaking_the_turn(self):
        set_mode("plan", source="test")
        with mock.patch.object(plugin, "build_plan_prompt", side_effect=RuntimeError("boom")):
            context = self.context()
        self.assertIn(SKILL_POINTER, context)

    def test_an_empty_user_message_is_fine(self):
        set_mode("plan", source="test")
        self.assertIn(SKILL_POINTER, self.context(user_message=""))


class TestPerSessionDirective(PlanDirectiveTestCase):
    def setUp(self):
        super().setUp()  # temp HERMES_HOME: a write here must never reach the live state file
        plugin.settings.set_reader(None)
        self.addCleanup(plugin.settings.set_reader, None)

    def test_the_directive_fires_for_a_plan_session(self):
        state.set_session_mode("s-plan", "plan", source="test")
        result = plugin.plan_directive("do the thing", session_id="s-plan")
        self.assertIsInstance(result, dict)
        self.assertIn("context", result)

    def test_the_directive_is_silent_for_a_writable_session(self):
        state.set_session_mode("s-writable", "writable", source="test")
        self.assertIsNone(plugin.plan_directive("do the thing", session_id="s-writable"))

    def test_a_plan_session_does_not_hand_another_sessions_turn_to_the_plan_skill(self):
        state.set_session_mode("s-plan", "plan", source="test")
        state.set_session_mode("s-writable", "writable", source="test")
        self.assertIsNone(plugin.plan_directive("go", session_id="s-writable"))
        self.assertIsNotNone(plugin.plan_directive("go", session_id="s-plan"))


if __name__ == "__main__":
    unittest.main()
