"""The one setting: the mode a NEW session starts in.

The manifest declaration is part of the contract — without it Hermes renders no form
and `save_plugin_settings` refuses the key, so the dashboard could not write it.
"""

from __future__ import annotations

import unittest

from plugin_under_test import PLUGIN_DIR, load_submodule

settings = load_submodule("settings")
ledger = load_submodule("state")


class TestDefaultMode(unittest.TestCase):
    def tearDown(self):
        settings.set_reader(None)

    def test_without_a_reader_the_default_is_readonly(self):
        self.assertEqual(settings.default_mode(), "readonly")

    def test_a_declared_value_is_returned(self):
        settings.set_reader(lambda key, default: "plan")
        self.assertEqual(settings.default_mode(), "plan")

    def test_a_garbage_value_reads_as_readonly(self):
        settings.set_reader(lambda key, default: "yolo")
        self.assertEqual(settings.default_mode(), "readonly")

    def test_a_non_string_value_reads_as_readonly(self):
        settings.set_reader(lambda key, default: 3)
        self.assertEqual(settings.default_mode(), "readonly")

    def test_the_reader_is_asked_for_default_mode(self):
        seen = []
        settings.set_reader(lambda key, default: seen.append(key) or "readonly")
        settings.default_mode()
        self.assertEqual(seen, [settings.SETTING])
        self.assertEqual(settings.SETTING, "default_mode")


class TestManifestDeclaration(unittest.TestCase):
    """`config_schema` is what makes the setting real: validated, rendered, writable."""

    def setUp(self):
        import yaml  # the venv has PyYAML; the loader reads plugin.yaml the same way

        self.manifest = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
        self.spec = (self.manifest.get("config_schema") or {}).get("default_mode")

    def test_the_manifest_declares_default_mode(self):
        self.assertIsInstance(self.spec, dict, "plugin.yaml has no config_schema.default_mode")

    def test_the_default_is_readonly_and_the_choices_are_the_modes(self):
        self.assertEqual(self.spec.get("default"), "readonly")
        self.assertEqual(tuple(self.spec.get("choices") or ()), ledger.MODES)
        self.assertEqual(str(self.spec.get("type")), "str")


    def test_the_manifest_declares_the_startup_reset_and_defaults_it_off(self):
        spec = (self.manifest.get("config_schema") or {}).get("reset_sessions_on_startup")
        self.assertIsInstance(spec, dict, "plugin.yaml has no config_schema.reset_sessions_on_startup")
        self.assertEqual(str(spec.get("type")), "bool")
        self.assertIs(spec.get("default"), False)


class TestResetOnStartup(unittest.TestCase):
    """Opt-in, and opt-in means the literal boolean: `"true"` in quotes is not true."""

    def tearDown(self):
        settings.set_reader(None)

    def test_without_a_reader_it_is_off(self):
        self.assertIs(settings.reset_on_startup(), False)

    def test_a_literal_true_enables_it(self):
        settings.set_reader(lambda key, default: True)
        self.assertIs(settings.reset_on_startup(), True)

    def test_anything_but_true_is_off(self):
        for value in ("true", 1, "yes", None, [True]):
            settings.set_reader(lambda key, default, value=value: value)
            self.assertIs(settings.reset_on_startup(), False, repr(value))

    def test_the_reader_is_asked_for_this_key(self):
        seen = []
        settings.set_reader(lambda key, default: seen.append(key) or False)
        settings.reset_on_startup()
        self.assertEqual(seen, [settings.RESET_SETTING])
        self.assertEqual(settings.RESET_SETTING, "reset_sessions_on_startup")


if __name__ == "__main__":
    unittest.main()
