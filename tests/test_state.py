"""Mode state: the guard's single source of truth and its fail-safe default."""

from __future__ import annotations

import json
import os
import tempfile
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
        self.state_file = Path(tmp.name) / "readonly-guard.state"
        env = mock.patch.dict(os.environ, {"HERMES_HOME": tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def write_raw(self, text: str) -> None:
        self.state_file.write_text(text)


class TestReadMode(StateTestCase):
    def test_missing_file_reads_as_the_restrictive_default(self):
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
        self.assertFalse(self.state_file.with_suffix(".tmp").exists())

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


if __name__ == "__main__":
    unittest.main()
