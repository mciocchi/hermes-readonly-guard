"""The session table: one mode per session, nothing global.

Every test points ``HERMES_HOME`` at a temp dir, so none of them can read or write the
user's live ``~/.hermes/readonly-guard.state``.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from plugin_under_test import load_state

state = load_state()


class StateCase(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        patcher = mock.patch.dict(os.environ, {"HERMES_HOME": self._home.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_raw(self, text: str) -> None:
        Path(self._home.name, state.STATE_FILENAME).write_text(text, encoding="utf-8")


class TestSessionTable(StateCase):
    def test_a_missing_file_has_no_session_modes(self):
        self.assertIsNone(state.get_session_mode("s1"))

    def test_a_new_session_has_no_entry(self):
        state.set_session_mode("s1", "plan")
        self.assertIsNone(state.get_session_mode("s2"))

    def test_set_then_get_round_trips(self):
        state.set_session_mode("s1", "plan", source="test")
        self.assertEqual(state.get_session_mode("s1"), "plan")

    def test_two_sessions_hold_different_modes(self):
        state.set_session_mode("s1", "plan")
        state.set_session_mode("s2", "writable")
        self.assertEqual(state.get_session_mode("s1"), "plan")
        self.assertEqual(state.get_session_mode("s2"), "writable")

    def test_setting_one_session_leaves_the_others_alone(self):
        state.set_session_mode("s1", "plan")
        state.set_session_mode("s2", "writable")
        state.set_session_mode("s1", "readonly")
        self.assertEqual(state.get_session_mode("s2"), "writable")

    def test_set_rejects_an_unknown_mode(self):
        with self.assertRaises(ValueError):
            state.set_session_mode("s1", "yolo")
        self.assertIsNone(state.get_session_mode("s1"))

    def test_set_rejects_an_empty_session_id(self):
        """No global slot: an empty id is a caller bug, not a machine-wide write."""
        with self.assertRaises(ValueError):
            state.set_session_mode("", "writable")
        self.assertFalse(Path(self._home.name, state.STATE_FILENAME).exists())

    def test_a_non_object_file_reads_as_no_sessions(self):
        self.write_raw('["nope"]')
        self.assertIsNone(state.get_session_mode("s1"))
        state.set_session_mode("s1", "plan")  # still writable: the bad file is replaced
        self.assertEqual(state.get_session_mode("s1"), "plan")

    def test_entries_with_a_bad_mode_are_ignored(self):
        self.write_raw(json.dumps({"version": 2, "sessions": {
            "s1": {"mode": "yolo", "updated_at": 1},
            "s2": {"mode": "plan", "updated_at": 1},
        }}))
        self.assertIsNone(state.get_session_mode("s1"))
        self.assertEqual(state.get_session_mode("s2"), "plan")

    def test_a_pre_3_0_global_mode_grants_no_session_writable(self):
        """The old file described the machine. Nothing may inherit a looser posture."""
        self.write_raw(json.dumps({"mode": "writable", "enabled": False}))
        self.assertIsNone(state.get_session_mode("s1"))
        self.assertEqual(state.status("s1", default="readonly")["mode"], "readonly")

    def test_the_write_is_atomic_under_concurrency(self):
        """Three writers, distinct sessions: no lost entries, no FileNotFoundError."""
        errors = []

        def writer(prefix):
            # 3 x 50 stays under SESSION_CAP, so nothing is evicted and every write
            # must be visible: the race this catches is a shared temp filename.
            for i in range(50):
                try:
                    state.set_session_mode(f"{prefix}{i}", "plan", source="race")
                except Exception as exc:  # noqa: BLE001 - the failure is the finding
                    errors.append(exc)
                    return

        threads = [threading.Thread(target=writer, args=(f"t{n}-",)) for n in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(state._sessions()), 150)

    def test_the_table_is_pruned_to_the_cap(self):
        now = time.time()
        # All seeded entries are in the PAST, oldest first, so the new write is the
        # newest and the eviction has to drop s0 — not the write itself.
        table = {
            f"s{i}": {"mode": "plan", "updated_at": now - 1000 + i}
            for i in range(state.SESSION_CAP + 5)
        }
        self.write_raw(json.dumps({"version": 2, "sessions": table}))
        state.set_session_mode("new", "writable")
        sessions = state._sessions()
        self.assertEqual(len(sessions), state.SESSION_CAP)
        self.assertIn("new", sessions)
        self.assertNotIn("s0", sessions, "the oldest entry should be the one dropped")
        self.assertIn("s9", sessions)


class TestStatus(StateCase):
    def test_status_reports_the_session_default_and_the_source(self):
        state.set_session_mode("s1", "plan", source="slash_command")
        payload = state.status("s1", default="readonly")
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["source"], "session")
        self.assertEqual(payload["default"], "readonly")
        self.assertEqual(payload["session"], "s1")
        self.assertEqual(payload["modes"], list(state.MODES))
        self.assertTrue(payload["blocking"])

    def test_status_without_a_session_reports_the_default_as_the_mode(self):
        payload = state.status("", default="writable")
        self.assertEqual(payload["mode"], "writable")
        self.assertEqual(payload["source"], "default")
        self.assertEqual(payload["session"], "")
        self.assertFalse(payload["blocking"])


def _raising(*_args, **_kwargs):
    """A resolver that fails, for the fallback path."""
    raise RuntimeError("resolver unavailable")


class TestHomeResolver(StateCase):
    """The state file must land in HERMES's home, never in an assumed ``~/.hermes``.

    ``%LOCALAPPDATA%/hermes`` is the Windows default, and a profile or a session override
    moves the home on every platform. Hardcoding the POSIX path writes the mode somewhere
    nobody reads, which looks exactly like the switch doing nothing.
    """

    def test_the_state_file_follows_hermes_own_resolver(self):
        home = Path(self._home.name) / "localappdata"
        with mock.patch.object(state, "_hermes_home_resolver", lambda: home):
            self.assertEqual(state.state_path(), home / state.STATE_FILENAME)

    def test_a_resolver_that_raises_falls_back_to_HERMES_HOME(self):
        with mock.patch.object(state, "_hermes_home_resolver", _raising):
            self.assertEqual(state.state_path(), Path(self._home.name) / state.STATE_FILENAME)

    def test_a_missing_resolver_falls_back_to_HERMES_HOME(self):
        with mock.patch.object(state, "_hermes_home_resolver", None):
            self.assertEqual(state.state_path(), Path(self._home.name) / state.STATE_FILENAME)


def _refused(src, dst):
    raise PermissionError(13, "The process cannot access the file")


class TestReplaceUnderReader(StateCase):
    """POSIX renames an open path; Windows returns PermissionError until the reader closes.

    The window is milliseconds (a dashboard poll reading the table while ``/readonly``
    writes), so a short retry is the whole fix — but it has to be a retry, and the last
    error still has to reach the caller rather than being swallowed into a silent no-op.
    """

    def test_a_write_survives_a_reader_holding_the_file_open(self):
        real_replace = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, "The process cannot access the file")
            return real_replace(src, dst)

        with mock.patch("os.replace", flaky):
            state.set_session_mode("s-retry", "plan", source="test")
        self.assertEqual(state.get_session_mode("s-retry"), "plan")
        self.assertEqual(len(calls), 3, "expected two refusals and then a third attempt")

    def test_the_last_error_is_raised_when_every_attempt_fails(self):
        with mock.patch("os.replace", _refused):
            with self.assertRaises(PermissionError):
                state.set_session_mode("s-doomed", "plan", source="test")
        self.assertIsNone(state.get_session_mode("s-doomed"))

    def test_a_failed_write_leaves_no_temp_file_behind(self):
        with mock.patch("os.replace", _refused):
            with self.assertRaises(PermissionError):
                state.set_session_mode("s-doomed", "plan", source="test")
        leftovers = sorted(p.name for p in Path(self._home.name).iterdir() if p.name.endswith(".tmp"))
        self.assertEqual(leftovers, [], "the temp file must be cleaned up on failure")


if __name__ == "__main__":
    unittest.main()
