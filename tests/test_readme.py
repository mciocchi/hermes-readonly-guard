"""The README is the plugin's front page: the catalog renders this file at the pinned SHA.

These checks are structural because the content is prose. They pin the order a reader
needs (what it is, install, modes, limits, troubleshooting), the things the docs
renderer forbids (raw HTML, third-party images), and the two facts that go stale
silently: the repository the install command names, and the licence.
"""

from __future__ import annotations

import re
import unittest

import yaml

from plugin_under_test import PLUGIN_DIR

README = PLUGIN_DIR / "README.md"
TEXT = README.read_text()

#: Reader-facing sections, in the order a first-time visitor needs them.
SECTIONS = [
    "# readonly-guard",
    "## Why",
    "## Install",
    "## The three modes",
    "## Switching it",
    "## The default for new sessions",
    "## What it does not protect against",
    "## Troubleshooting",
    "## Uninstall",
    "## Licence",
]

#: Tags that would be dropped by the docs renderer, so a reader would see the raw text.
HTML_TAG_RE = re.compile(r"<(a|img|div|span|br|hr|p|table|tr|td|details|summary|kbd|sub|sup)\b[^>]*>", re.I)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


class TestStructure(unittest.TestCase):
    def test_the_sections_a_reader_needs_are_present_in_order(self):
        positions = []
        for heading in SECTIONS:
            self.assertIn(heading, TEXT, f"missing section: {heading}")
            positions.append(TEXT.index(heading))
        self.assertEqual(positions, sorted(positions), "sections are out of order")

    def test_the_install_section_names_the_repository_and_the_plugin(self):
        """The install command is the one thing a reader copies. It has to name the repo
        the catalog entry points at, and the plugin id that `enable` takes."""
        entry = yaml.safe_load((PLUGIN_DIR / "catalog-entry.yaml").read_text())
        repo = str(entry["repo"]).rstrip("/").removeprefix("https://github.com/")
        install = TEXT.split("## Install", 1)[1].split("\n## ", 1)[0]
        self.assertIn(f"hermes plugins install {repo}", install)
        self.assertIn("hermes plugins enable readonly-guard", install)

    def test_the_readme_names_the_licence_the_manifest_declares(self):
        licence = str(yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text())["license"])
        section = TEXT.split("## Licence", 1)[1]
        self.assertIn(licence, section)
        self.assertIn("LICENSE", section)


class TestRenderability(unittest.TestCase):
    def test_no_raw_html_that_the_docs_renderer_would_drop(self):
        found = HTML_TAG_RE.findall(TEXT)
        self.assertEqual(found, [], f"raw HTML is stripped by the docs renderer: {found}")

    def test_every_image_is_on_a_github_host(self):
        """The docs renderer resolves images against the pinned tree, so a badge from a
        third-party host is either blocked or a network call the site never makes."""
        for target in IMAGE_RE.findall(TEXT):
            self.assertTrue(
                target.startswith(("https://raw.githubusercontent.com/", "https://github.com/", "./")),
                f"image not on a GitHub host: {target}",
            )


if __name__ == "__main__":
    unittest.main()
