"""The catalog card image: docs/banner.png, rendered from docs/banner.html.

The image is what a user sees before reading anything. These checks prove the file
exists, is 2:1 (the schema's requirement), uses the colours the plugin actually ships,
and that the entry's image is the banner at the entry's own commit.
"""

from __future__ import annotations

import struct
import unittest

import yaml

from plugin_under_test import PLUGIN_DIR
from test_desktop_contract import tones

BANNER = PLUGIN_DIR / "docs" / "banner.png"
SOURCE = PLUGIN_DIR / "docs" / "banner.html"
ENTRY = PLUGIN_DIR / "catalog-entry.yaml"

def png_size(path) -> tuple[int, int]:
    """(width, height) from the PNG IHDR chunk — no imaging library required."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG file"
    return struct.unpack(">II", data[16:24])


class TestBanner(unittest.TestCase):
    def test_the_banner_and_its_source_exist(self):
        self.assertTrue(SOURCE.is_file(), "docs/banner.html is the reviewable source")
        self.assertTrue(BANNER.is_file(), "docs/banner.png is the rendered card image")

    def test_the_banner_is_two_to_one_and_large_enough(self):
        width, height = png_size(BANNER)
        self.assertEqual(width, 2 * height, f"{width}x{height} is not 2:1")
        self.assertGreaterEqual(width, 1200, f"{width}px is too small for a card")

    def test_the_banner_uses_the_colours_the_desktop_half_ships(self):
        """A banner that drifts from TONES is wrong in a way nothing else can see."""
        html = SOURCE.read_text(encoding="utf-8")
        for mode, (bg, fg) in tones().items():
            self.assertIn(bg, html, f"{mode}'s fill {bg} is missing from the banner")
            self.assertIn(fg, html, f"{mode}'s text colour {fg} is missing from the banner")

    def test_the_banner_shows_the_writable_lease(self):
        """The card is the first thing a user sees; it must show the mode as it now is.

        The chip renders `writable · 24m`, so the illustration copies that shape — the
        middle dot, a space, digits, `m` — rather than a bare `writable` that describes a
        version of the control that no longer exists.
        """
        html = SOURCE.read_text(encoding="utf-8")
        # The countdown lives in a span of its own, so allow a little markup between the
        # word and the dot rather than requiring them to be adjacent text.
        self.assertRegex(html, r"writable.{0,120}·\s*\d+m")

    def test_the_entry_pins_a_full_sha_and_the_image_that_sha_carries(self):
        """The published entry names one commit, and its image is that commit's banner.

        Exact equality rather than a pattern: the catalog renders the README and this
        image from the same SHA, so an image pointing at a different commit is a card
        that survives a code change it never mentions. A later `sha` bump fails here
        until `image:` follows it, which is the reminder this file exists to give.
        """
        entry = yaml.safe_load(ENTRY.read_text(encoding="utf-8"))
        sha = str(entry.get("sha") or "")
        image = str(entry.get("image") or "")
        self.assertRegex(sha, r"^[0-9a-f]{40}$", "a published entry needs a full commit SHA")
        self.assertEqual(
            image,
            "https://raw.githubusercontent.com/mciocchi/hermes-readonly-guard/"
            f"{sha}/docs/banner.png",
            "image must be the banner at the entry's own sha",
        )


if __name__ == "__main__":
    unittest.main()
