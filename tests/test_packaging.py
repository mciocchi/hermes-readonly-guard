"""What a publisher and a reviewer check before the code is ever run.

Every assertion here is about a file that says something about the plugin — the
licence, the manifest's metadata, the repository URLs, the version strings that must
agree, and the catalog entry's declared capabilities. All of it is cheap to drift and
none of it breaks a test suite otherwise.
"""

from __future__ import annotations

import json
import re
import unittest

import yaml

from plugin_under_test import PLUGIN_DIR, load_plugin

plugin = load_plugin()

MANIFEST = PLUGIN_DIR / "plugin.yaml"
DASHBOARD = PLUGIN_DIR / "dashboard" / "manifest.json"
ENTRY = PLUGIN_DIR / "catalog-entry.yaml"


def read_manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text()) or {}


class FakeContext:
    """Records what register() wires up; only the registrars this plugin uses."""

    def __init__(self):
        self.hooks = []
        self.commands = {}
        self.settings = {}

    def register_hook(self, hook_name, callback):
        self.hooks.append(hook_name)

    def register_command(self, name, handler=None, description="", args_hint=""):
        self.commands[name] = handler

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


class TestLicenceAndUrl(unittest.TestCase):
    def test_the_manifest_declares_mit_and_the_project_url(self):
        manifest = read_manifest()
        self.assertEqual(manifest.get("license"), "MIT")
        self.assertEqual(
            manifest.get("homepage"), "https://github.com/mciocchi/hermes-readonly-guard/"
        )

    def test_the_licence_file_is_mit_for_the_copyright_holder(self):
        text = (PLUGIN_DIR / "LICENSE").read_text()
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2026 Matt Ciocchi", text)
        self.assertIn("Permission is hereby granted, free of charge", text)

    def test_the_manifest_does_not_declare_requires_hermes(self):
        """Deliberate omission, pinned.

        A floor the running core fails makes the LOADER skip the plugin, silently, and
        `load_plugin()` in tests bypasses that gate — so a wrong value would be invisible
        here and fatal on a user's machine. Rather than guess, the field stays out.
        """
        self.assertNotIn(
            "requires_hermes", read_manifest(),
            "decided against: an over-tight floor makes the loader skip the plugin and no test sees it",
        )


class TestVersionsAgree(unittest.TestCase):
    """Three files state the version. A release bumps all three or none."""

    def test_the_manifest_the_dashboard_and_the_entry_agree(self):
        manifest_version = str(read_manifest().get("version"))
        dashboard_version = str(json.loads(DASHBOARD.read_text())["version"])
        entry_version = str(yaml.safe_load(ENTRY.read_text())["version"])
        self.assertEqual(
            {manifest_version, dashboard_version, entry_version},
            {"3.3"},
            f"manifest={manifest_version} dashboard={dashboard_version} entry={entry_version}",
        )


class TestCatalogEntry(unittest.TestCase):
    """Rule 6 of the catalog: declared capabilities must match what is registered."""

    def setUp(self):
        self.entry = yaml.safe_load(ENTRY.read_text())
        ctx = FakeContext()
        plugin.register(ctx)
        self.registered_hooks = set(ctx.hooks)
        self.capabilities = self.entry.get("capabilities") or {}

    def test_the_entry_names_the_plugin_and_a_maintainer(self):
        self.assertEqual(self.entry["name"], "readonly-guard")
        self.assertEqual(self.entry["maintainer"], "mciocchi")
        self.assertIn(self.entry["category"], {
            "desktop", "memory", "platform", "web", "tools", "voice", "automation", "models", "general",
        })
        self.assertIn(self.entry["tier"], {"official", "community"})

    def test_the_entry_points_at_the_published_repository(self):
        """The repo is `hermes-readonly-guard`; the catalog KEY stays `readonly-guard`,
        because that is what users search and install. The manifest homepage may end in a
        slash (it is a browser URL); the clone URL must not, because the loader appends
        paths to it."""
        homepage = str(read_manifest().get("homepage") or "")
        self.assertEqual(homepage, "https://github.com/mciocchi/hermes-readonly-guard/")
        self.assertEqual(self.entry["repo"].rstrip("/"), homepage.rstrip("/"))
        self.assertFalse(self.entry["repo"].endswith("/"), "repo must be the bare clone URL")
        self.assertEqual(self.entry["docs_url"].rstrip("/"), homepage.rstrip("/"))

    def test_the_declared_hooks_are_exactly_the_registered_ones(self):
        self.assertEqual(set(self.capabilities.get("provides_hooks") or []), self.registered_hooks)

    def test_nothing_else_is_claimed(self):
        """tools, middleware and env: this plugin registers none of them."""
        self.assertEqual(self.capabilities.get("provides_tools"), [])
        self.assertEqual(self.capabilities.get("provides_middleware"), [])
        self.assertEqual(self.capabilities.get("requires_env"), [])


if __name__ == "__main__":
    unittest.main()
