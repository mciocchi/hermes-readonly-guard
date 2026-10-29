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




class TestWritableExpirySetting(unittest.TestCase):
    def tearDown(self):
        settings.set_reader(None)

    def test_without_a_reader_it_is_thirty_minutes(self):
        self.assertEqual(settings.writable_expiry_minutes(), 30)

    def test_a_declared_integer_wins(self):
        settings.set_reader(lambda key, default: 5)
        self.assertEqual(settings.writable_expiry_minutes(), 5)

    def test_zero_disables_it(self):
        settings.set_reader(lambda key, default: 0)
        self.assertEqual(settings.writable_expiry_minutes(), 0)

    def test_garbage_reads_as_thirty(self):
        for value in ("soon", -5, None, 3.5, True):
            settings.set_reader(lambda key, default, value=value: value)
            self.assertEqual(settings.writable_expiry_minutes(), 30, repr(value))

    def test_the_reader_is_asked_for_this_key(self):
        seen = []
        settings.set_reader(lambda key, default: seen.append(key) or 30)
        settings.writable_expiry_minutes()
        self.assertEqual(seen, [settings.EXPIRY_SETTING])
        self.assertEqual(settings.EXPIRY_SETTING, "writable_expiry_minutes")

    def test_the_manifest_declares_it(self):
        import yaml

        manifest = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
        spec = (manifest.get("config_schema") or {}).get("writable_expiry_minutes")
        self.assertIsInstance(spec, dict, "plugin.yaml has no config_schema.writable_expiry_minutes")
        self.assertEqual(str(spec.get("type")), "int")
        self.assertEqual(spec.get("default"), 30)


if __name__ == "__main__":
    unittest.main()
