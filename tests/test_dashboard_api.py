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
        body = self.client.get("/api/plugins/readonly-guard/state").json()
        self.assertEqual(body["mode"], "readonly")   # no file yet -> restrictive default
        self.assertEqual(body["modes"], ["readonly", "plan", "writable"])
        self.assertTrue(body["state_file"].endswith("readonly-guard.state"))

    def test_blocking_is_false_only_for_writable(self):
        for mode, expected in (("readonly", True), ("plan", True), ("writable", False)):
            self.client.post("/api/plugins/readonly-guard/state", json={"mode": mode})
            body = self.client.get("/api/plugins/readonly-guard/state").json()
            self.assertIs(body["blocking"], expected, mode)


class TestPostState(DashboardApiTestCase):
    def test_setting_a_mode_writes_it(self):
        body = self.client.post("/api/plugins/readonly-guard/state", json={"mode": "plan"}).json()
        self.assertEqual(body["mode"], "plan")
        self.assertEqual(self.mode_on_disk(), "plan")

    def test_an_unknown_mode_is_an_error_and_changes_nothing(self):
        self.client.post("/api/plugins/readonly-guard/state", json={"mode": "readonly"})
        body = self.client.post("/api/plugins/readonly-guard/state", json={"mode": "yolo"}).json()
        self.assertIn("error", body)
        self.assertEqual(self.mode_on_disk(), "readonly")

    def test_a_missing_mode_is_an_error(self):
        self.assertIn("error", self.client.post("/api/plugins/readonly-guard/state", json={}).json())

    def test_the_legacy_enabled_body_is_rejected(self):
        """1.1's shape is gone; the UI and this API ship together."""
        body = self.client.post("/api/plugins/readonly-guard/state", json={"enabled": True}).json()
        self.assertIn("error", body)


class TestToggle(DashboardApiTestCase):
    def test_toggle_cycles_readonly_plan_writable_readonly(self):
        seen = []
        for _ in range(4):
            seen.append(self.client.post("/api/plugins/readonly-guard/toggle").json()["mode"])
        self.assertEqual(seen, ["plan", "writable", "readonly", "plan"])


if __name__ == "__main__":
    unittest.main()
