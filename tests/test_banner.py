"""The catalog card image: docs/banner.png, rendered from docs/banner.html.

The image is what a user sees before reading anything. These checks prove the file
exists, is 2:1 (the schema's requirement), uses the colours the plugin actually ships,
and that the entry never carries a URL that is not pinned to a commit.
"""

from __future__ import annotations

import re
import struct
import unittest

import yaml

from plugin_under_test import PLUGIN_DIR
from test_desktop_contract import tones

BANNER = PLUGIN_DIR / "docs" / "banner.png"
SOURCE = PLUGIN_DIR / "docs" / "banner.html"
ENTRY = PLUGIN_DIR / "catalog-entry.yaml"

#: A raw URL of this repository at a full commit SHA, ending in the banner's own path.
PINNED_IMAGE_RE = re.compile(
    r"^https://raw\.githubusercontent\.com/mciocchi/hermes-readonly-guard/"
    r"[0-9a-f]{40}/docs/banner\.png$"
)


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
        html = SOURCE.read_text()
        for mode, (bg, fg) in tones().items():
            self.assertIn(bg, html, f"{mode}'s fill {bg} is missing from the banner")
            self.assertIn(fg, html, f"{mode}'s text colour {fg} is missing from the banner")

    def test_the_entry_either_omits_the_image_or_pins_one(self):
        image = str(yaml.safe_load(ENTRY.read_text()).get("image") or "")
        self.assertTrue(
            image == "" or PINNED_IMAGE_RE.match(image),
            f"image must be empty or pinned to a 40-character SHA, got {image!r}",
        )


if __name__ == "__main__":
    unittest.main()
