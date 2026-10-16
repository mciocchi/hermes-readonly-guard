"""The dashboard half: the mode API the desktop chip drives.

Needs fastapi + httpx, which live in the Hermes venv — run the suite with
$HERMES_REPO/venv/bin/python.
"""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

PLUGIN_DIR = Path(__file__).resolve().parents[1]

STATE_URL = "/api/plugins/readonly-guard/state"
TOGGLE_URL = "/api/plugins/readonly-guard/toggle"


def _load_router():
    """Load dashboard/plugin_api.py the way the web server does: by file path."""
    spec = importlib.util.spec_from_file_location(
        "readonly_guard_dashboard_api", PLUGIN_DIR / "dashboard" / "plugin_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # puts the plugin dir on sys.path itself
    return module.router


app = FastAPI()
app.include_router(_load_router(), prefix="/api/plugins/readonly-guard")


class DashboardApiTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state_file = Path(tmp.name) / "readonly-guard.state"
        env = mock.patch.dict(os.environ, {"HERMES_HOME": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app)

    def mode_on_disk(self) -> str:
        return json.loads(self.state_file.read_text())["mode"]


class TestGetState(DashboardApiTestCase):
    def test_state_reports_the_mode_the_modes_and_the_file(self):
        body = self.client.get(STATE_URL).json()
        self.assertEqual(body["mode"], "readonly")   # no file yet -> restrictive default
        self.assertEqual(body["modes"], ["readonly", "plan", "writable"])
        self.assertTrue(body["state_file"].endswith("readonly-guard.state"))

    def test_blocking_is_false_only_for_writable(self):
        for mode, expected in (("readonly", True), ("plan", True), ("writable", False)):
            self.client.post(STATE_URL, json={"mode": mode})
            body = self.client.get(STATE_URL).json()
            self.assertIs(body["blocking"], expected, mode)

    def test_the_payload_keeps_the_1x_enabled_key_for_a_stale_client(self):
        """The desktop half already deployed in the app reads `enabled`, not `mode`.

        Dropping the key would leave the live chip reporting "writable" while the guard
        is actually blocking — a safety indicator that lies. It is removed only when the
        copy in the app has been refreshed.
        """
        self.assertIs(self.client.get(STATE_URL).json()["enabled"], True)   # no file -> readonly
        self.client.post(STATE_URL, json={"mode": "writable"})
        self.assertIs(self.client.get(STATE_URL).json()["enabled"], False)


class TestPostState(DashboardApiTestCase):
    def test_setting_a_mode_writes_it(self):
        body = self.client.post(STATE_URL, json={"mode": "plan"}).json()
        self.assertEqual(body["mode"], "plan")
        self.assertEqual(self.mode_on_disk(), "plan")

    def test_a_rejected_mode_leaves_the_file_byte_identical(self):
        """Compare the whole file, not the key the request tried to write.

        Re-reading only `mode` lets a handler that writes before validating pass, even
        though the test's name claims it proves nothing changed.
        """
        self.client.post(STATE_URL, json={"mode": "plan"})
        before = self.state_file.read_bytes()
        body = self.client.post(STATE_URL, json={"mode": "yolo"}).json()
        self.assertIn("error", body)
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_a_rejected_mode_on_a_fresh_home_creates_no_state_file(self):
        self.assertFalse(self.state_file.exists())
        body = self.client.post(STATE_URL, json={"mode": "yolo"}).json()
        self.assertIn("error", body)
        self.assertFalse(self.state_file.exists())

    def test_a_missing_mode_is_an_error_and_changes_nothing(self):
        self.client.post(STATE_URL, json={"mode": "plan"})
        before = self.state_file.read_bytes()
        for body in ({}, None):
            self.assertIn("error", self.client.post(STATE_URL, json=body).json(), body)
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_the_legacy_enabled_body_is_rejected(self):
        """1.1's shape is gone; the UI and this API ship together."""
        body = self.client.post(STATE_URL, json={"enabled": True}).json()
        self.assertIn("error", body)

    def test_a_non_object_body_is_rejected_before_the_handler_runs(self):
        """FastAPI validates the `dict | None` annotation, so the handler never sees it.

        That makes the documented `{"error": ...}` envelope non-universal: a malformed
        body answers 422 with `{"detail": ...}` instead. Pinned here because the chip's
        error path depends on which one it gets.
        """
        self.client.post(STATE_URL, json={"mode": "plan"})
        before = self.state_file.read_bytes()
        for payload in ([], "plan", 42, True):
            response = self.client.post(STATE_URL, json=payload)
            self.assertEqual(response.status_code, 422, payload)
        self.assertEqual(self.state_file.read_bytes(), before)


class TestToggle(DashboardApiTestCase):
    def test_toggle_cycles_readonly_plan_writable_readonly(self):
        seen = []
        for _ in range(4):
            seen.append(self.client.post(TOGGLE_URL).json()["mode"])
        self.assertEqual(seen, ["plan", "writable", "readonly", "plan"])


if __name__ == "__main__":
    unittest.main()
