"""Mode state: the guard's single source of truth and its fail-safe default."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from plugin_under_test import load_state

state = load_state()


class StateTestCase(unittest.TestCase):
    """Every case runs against a throwaway HERMES_HOME: the live switch is never touched."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        # STATE_FILENAME, not a literal: a renamed state file must fail these tests
        # rather than silently turn them into tests of the missing-file path.
        self.state_file = self.tmp / state.STATE_FILENAME
        env = mock.patch.dict(os.environ, {"HERMES_HOME": tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def write_raw(self, text: str) -> None:
        self.state_file.write_text(text)


class TestReadMode(StateTestCase):
    def test_missing_file_reads_as_the_restrictive_default(self):
        self.assertFalse(self.state_file.exists())
        self.assertEqual(state.read_mode(), state.MODE_READONLY)

    def test_each_mode_round_trips(self):
        for mode in state.MODES:
            state.set_mode(mode, source="test")
            self.assertEqual(state.read_mode(), mode)

    def test_an_unrecognised_mode_fails_closed(self):
        self.write_raw('{"mode": "yolo"}')
        self.assertEqual(state.read_mode(), state.MODE_READONLY)

    def test_a_corrupt_file_fails_closed(self):
        self.write_raw("{not json")
        self.assertEqual(state.read_mode(), state.MODE_READONLY)

    def test_a_1x_enabled_false_file_migrates_to_writable(self):
        self.write_raw('{"enabled": false, "updated_at": 1.0, "updated_by": "dashboard"}')
        self.assertEqual(state.read_mode(), state.MODE_WRITABLE)

    def test_a_1x_enabled_true_file_reads_as_readonly(self):
        self.write_raw('{"enabled": true}')
        self.assertEqual(state.read_mode(), state.MODE_READONLY)

    def test_the_mode_key_wins_over_the_legacy_key(self):
        self.write_raw('{"mode": "plan", "enabled": false}')
        self.assertEqual(state.read_mode(), state.MODE_PLAN)


class TestSetMode(StateTestCase):
    def test_an_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            state.set_mode("yolo", source="test")

    def test_the_write_is_recorded_and_leaves_no_temp_file(self):
        payload = state.set_mode("plan", source="unit-test")
        self.assertEqual(payload["enabled"], True)
        on_disk = json.loads(self.state_file.read_text())
        self.assertEqual(on_disk["mode"], "plan")
        self.assertEqual(on_disk["enabled"], True)
        self.assertEqual(on_disk["updated_by"], "unit-test")
        # Globbed, not the old fixed ".tmp" name: whatever the writer stages through,
        # it must not survive the call.
        self.assertEqual(sorted(p.name for p in self.tmp.glob("*.tmp")), [])

    def test_writable_keeps_the_legacy_key_false(self):
        state.set_mode("writable", source="unit-test")
        self.assertFalse(json.loads(self.state_file.read_text())["enabled"])


class TestDerived(StateTestCase):
    def test_blocks_writes_is_false_only_for_writable(self):
        self.assertTrue(state.blocks_writes("readonly"))
        self.assertTrue(state.blocks_writes("plan"))
        self.assertFalse(state.blocks_writes("writable"))

    def test_blocks_writes_with_no_argument_reads_the_file(self):
        state.set_mode("writable", source="test")
        self.assertFalse(state.blocks_writes())

    def test_next_mode_cycles_readonly_plan_writable(self):
        self.assertEqual(state.next_mode("readonly"), "plan")
        self.assertEqual(state.next_mode("plan"), "writable")
        self.assertEqual(state.next_mode("writable"), "readonly")

    def test_next_mode_from_an_unknown_value_returns_the_default(self):
        self.assertEqual(state.next_mode("yolo"), state.MODE_READONLY)


class TestRobustness(StateTestCase):
    """The state file is shared and machine-wide, so its read and write paths must
    survive whatever a second writer (or a truncated file) leaves behind."""

    def test_a_valid_json_non_object_file_fails_closed_without_raising(self):
        """A file that parses but is not an object must read as the restrictive default.

        Raising here would be fail-CLOSED for the guard (Hermes turns a raising
        pre_tool_call into a block) but bricks every tool call behind a confusing
        error and 500s the dashboard's GET /state.
        """
        for payload in ("[]", "42", '"readonly"', "null", "true"):
            with self.subTest(payload=payload):
                self.write_raw(payload)
                self.assertEqual(state.read_mode(), state.MODE_READONLY)
                self.assertTrue(state.blocks_writes())

    def test_the_write_creates_a_missing_parent_directory(self):
        nested = self.tmp / "profiles" / "work"
        self.assertFalse(nested.exists())
        with mock.patch.dict(os.environ, {"HERMES_HOME": str(nested)}):
            state.set_mode("plan", source="test")
            self.assertEqual(state.read_mode(), state.MODE_PLAN)

    def test_concurrent_writers_never_raise_and_leave_a_parseable_file(self):
        """A race detector, not a proof.

        At this iteration count it reproduces against the earlier shared-temp-name
        writer — two FileNotFoundError from os.replace per run, in two independent
        scratch runs — and passes against the unique-name writer. It pins the
        invariant (no writer raises, the file always parses, nothing staged is left
        behind) rather than the mechanism, so a different correct writer passes too.
        """
        errors: list[BaseException] = []

        def writer(mode: str) -> None:
            try:
                for _ in range(2000):
                    state.set_mode(mode, source="test")
            except Exception as exc:  # noqa: BLE001 - the point is to record it
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(mode,)) for mode in state.MODES]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertIn(state.read_mode(), state.MODES)
        self.assertIn("mode", json.loads(self.state_file.read_text()))
        self.assertEqual(sorted(p.name for p in self.tmp.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
