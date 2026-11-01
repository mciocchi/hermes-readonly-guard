"""The HTTP half: one session per request, and the setting when there is no session.

The dashboard is what the desktop chip calls, so these tests are the chip's contract:
`?session=` names a session, a POST body may carry one, and a request with neither
edits the default that NEW sessions start with.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

try:  # Hermes ships fastapi for its dashboard; a bare venv does not
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError as exc:  # a module-level skip, not a loader error
    raise unittest.SkipTest(f"the dashboard half needs fastapi (Hermes provides it): {exc}")

from plugin_under_test import PLUGIN_DIR, load_submodule

sys.path.insert(0, str(PLUGIN_DIR))  # the dashboard half imports `state` top-level
state = load_submodule("state")


def load_api():
    """The dashboard module, loaded the way the gateway loads it (by path, standalone)."""
    spec = importlib.util.spec_from_file_location(
        "rg_dashboard_api_under_test", PLUGIN_DIR / "dashboard" / "plugin_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ApiCase(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        env = mock.patch.dict(os.environ, {"HERMES_HOME": self._home.name})
        env.start()
        self.addCleanup(env.stop)
        self.api = load_api()
        app = FastAPI()
        app.include_router(self.api.router)
        self.client = TestClient(app)
        # The default-for-new-sessions write goes through Hermes' config writer, which a
        # bare test interpreter cannot import. Record the call instead: what this test
        # owns is the seam — the id, the key, the value — not Hermes' own writer.
        self.written = []
        self.api._write_setting = self.written.append

    def setting_on_disk(self) -> str | None:
        path = Path(self._home.name) / "config.yaml"
        if not path.is_file():
            return None
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entry = ((data.get("plugins") or {}).get("entries") or {}).get("readonly-guard") or {}
        return (entry.get("settings") or {}).get("default_mode")


class TestGet(ApiCase):
    def test_get_returns_the_named_sessions_mode(self):
        state.set_session_mode("s1", "plan", source="test")
        payload = self.client.get("/state", params={"session": "s1"}).json()
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["source"], "session")
        self.assertEqual(payload["session"], "s1")
        self.assertNotIn("enabled", payload, "the 1.x key is gone in 3.0")

    def test_get_without_a_session_reports_the_default(self):
        payload = self.client.get("/state").json()
        self.assertEqual(payload["session"], "")
        self.assertEqual(payload["mode"], "readonly")
        self.assertEqual(payload["source"], "default")
        self.assertEqual(payload["default"], "readonly")
        self.assertTrue(payload["blocking"])

    def test_the_payload_reports_which_file_it_reads(self):
        payload = self.client.get("/state").json()
        self.assertEqual(payload["state_file"], str(state.state_path()))
        self.assertEqual(payload["modes"], list(state.MODES))

    def test_get_reports_blocking_for_a_writable_session(self):
        state.set_session_mode("s1", "writable", source="test")
        payload = self.client.get("/state", params={"session": "s1"}).json()
        self.assertFalse(payload["blocking"])


class TestPost(ApiCase):
    def test_post_with_a_session_leaves_other_sessions_alone(self):
        state.set_session_mode("s-other", "writable", source="test")
        response = self.client.post("/state", json={"mode": "readonly", "session": "s1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(state.get_session_mode("s1"), "readonly")
        self.assertEqual(state.get_session_mode("s-other"), "writable")
        self.assertIsNone(self.setting_on_disk(), "a session write must not touch the setting")

    def test_post_without_a_session_writes_the_default_setting(self):
        response = self.client.post("/state", json={"mode": "writable"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.written, [{"default_mode": "writable"}])
        self.assertEqual(response.json()["default"], "writable")
        self.assertEqual(state._sessions(), {}, "a default write must not invent a session")

    def test_post_echoes_the_session_it_wrote(self):
        body = {"mode": "plan", "session": "s9"}
        payload = self.client.post("/state", json=body).json()
        self.assertEqual(payload["session"], "s9")
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["source"], "session")

    def test_a_session_write_does_not_change_the_reported_default(self):
        self.client.post("/state", json={"mode": "writable", "session": "s1"})
        payload = self.client.get("/state", params={"session": "s1"}).json()
        self.assertEqual(payload["default"], "readonly")

    def test_a_bad_mode_is_rejected_and_nothing_is_written(self):
        response = self.client.post("/state", json={"mode": "yolo", "session": "s1"})
        self.assertIn("error", response.json())
        self.assertIsNone(state.get_session_mode("s1"))
        self.assertIsNone(self.setting_on_disk())

    def test_a_non_object_body_is_422_and_writes_nothing(self):
        response = self.client.post("/state", json=["writable"])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(state._sessions(), {})
        self.assertIsNone(self.setting_on_disk())

    def test_a_legacy_enabled_body_is_rejected(self):
        """1.x's `{enabled: true}` is not a mode — an unknown shape is a request the
        caller does not understand, not one to guess at."""
        response = self.client.post("/state", json={"enabled": True, "session": "s1"})
        self.assertIn("error", response.json())
        self.assertIsNone(state.get_session_mode("s1"))

    def test_toggle_advances_a_sessions_mode(self):
        state.set_session_mode("s1", "plan", source="test")
        payload = self.client.post("/toggle", json={"session": "s1"}).json()
        self.assertEqual(payload["mode"], "writable")
        self.assertEqual(state.get_session_mode("s1"), "writable")

    def test_toggle_without_a_session_advances_the_default(self):
        payload = self.client.post("/toggle", json={}).json()
        self.assertEqual(self.written, [{"default_mode": "plan"}])
        self.assertEqual(payload["mode"], "plan")

    def test_toggle_wraps_from_writable_back_to_readonly(self):
        state.set_session_mode("s1", "writable", source="test")
        payload = self.client.post("/toggle", json={"session": "s1"}).json()
        self.assertEqual(payload["mode"], "readonly")


class TestTheConfiguredDefault(ApiCase):
    """Report what the config says, not the constant (ticket 01-T007, invariant I5).

    `GET /state` is what the chip lights. Reporting `readonly` while the guard enforces
    `plan` tells the user they may write when they may not.

    The read lives behind `_plugin_fields`, the same seam style as `_write_setting`:
    Hermes' own `plugin_settings_fields` needs a Hermes interpreter, and what these tests
    own is that the payload is built from it, and that `settings.py` still validates.
    """

    PLAN = [
        {"key": "default_mode", "value": "plan"},
        {"key": "writable_expiry_minutes", "value": 30},
    ]

    def test_get_without_a_session_reports_the_configured_default(self):
        self.api._plugin_fields = lambda: self.PLAN
        payload = self.client.get("/state").json()
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["default"], "plan")
        self.assertEqual(payload["source"], "default")

    def test_get_for_a_session_with_no_entry_reports_the_configured_default(self):
        self.api._plugin_fields = lambda: self.PLAN
        payload = self.client.get("/state", params={"session": "never-seen"}).json()
        self.assertEqual(payload["mode"], "plan")
        self.assertEqual(payload["source"], "default")

    def test_a_configured_zero_expiry_is_reported(self):
        self.api._plugin_fields = lambda: [
            {"key": "default_mode", "value": "readonly"},
            {"key": "writable_expiry_minutes", "value": 0},
        ]
        self.assertEqual(self.client.get("/state").json()["expiry_minutes"], 0)
        state.set_session_mode("s1", "writable", source="test")
        payload = self.client.get("/state", params={"session": "s1"}).json()
        self.assertIsNone(payload["expires_in"], "0 means never expires, not 'expired'")

    def test_the_reported_default_matches_the_mode_the_guard_enforces(self):
        """I5: one payload field and one guard decision, read from the same config."""
        self.api._plugin_fields = lambda: self.PLAN
        guard_settings = load_submodule("settings")
        self.addCleanup(guard_settings.set_reader, None)
        guard_settings.set_reader(
            lambda key, default: "plan" if key == "default_mode" else default
        )
        payload = self.client.get("/state", params={"session": "never-seen"}).json()
        self.assertEqual(payload["mode"], guard_settings.default_mode())

    def test_a_malformed_value_still_reads_as_readonly(self):
        """`settings.py` keeps the only copy of the validation: a typo tightens."""
        self.api._plugin_fields = lambda: [
            {"key": "default_mode", "value": "yolo"},
            {"key": "writable_expiry_minutes", "value": -1},
        ]
        payload = self.client.get("/state").json()
        self.assertEqual(payload["default"], "readonly")
        self.assertEqual(payload["expiry_minutes"], 30)

    def test_the_reader_falls_back_when_hermes_is_not_importable(self):
        def no_hermes():
            raise ImportError("no hermes_cli on this interpreter")

        self.api._plugin_fields = no_hermes
        payload = self.client.get("/state").json()
        self.assertEqual(payload["default"], "readonly")
        self.assertEqual(payload["expiry_minutes"], 30)


if __name__ == "__main__":
    unittest.main()
