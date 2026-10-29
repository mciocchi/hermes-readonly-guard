"""Static contract checks for the desktop half.

There is no way to render the app's UI from a terminal, and the two failure modes that
matter here are silent: an identifier that is not exported by the SDK, and a
contribution registered into a dead area id — in both cases the plugin loads,
registers, and simply never appears. These checks parse the file rather than run it.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

from plugin_under_test import PLUGIN_DIR

SOURCE = (PLUGIN_DIR / "desktop" / "plugin.js").read_text(encoding="utf-8")

def sdk_barrel() -> Path | None:
    """The desktop app's SDK barrel — the authority on what a plugin may import.

    Found, never hardcoded: a path from one machine makes this test skip silently
    everywhere else, which is the same as deleting it. Candidates, in order: an explicit
    ``HERMES_REPO``, the checkout the running interpreter belongs to
    (``<repo>/venv/bin/python`` -> three parents up), and the default install location.
    ``None`` means the Desktop sources are not on this machine.
    """
    candidates = [Path(os.environ["HERMES_REPO"])] if os.environ.get("HERMES_REPO") else []
    candidates.append(Path(sys.executable).resolve().parents[2])
    candidates.append(Path.home() / ".hermes" / "hermes-agent")
    for root in candidates:
        barrel = root / "apps" / "desktop" / "src" / "sdk" / "index.ts"
        if barrel.is_file():
            return barrel
    return None


#: ``None`` when this machine has no Desktop sources; the SDK check then skips.
SDK_BARREL = sdk_barrel()

SDK_IMPORT_RE = re.compile(r"import\s*\{([^}]+)\}\s*from\s*'@hermes/plugin-sdk'")
AREA_RE = re.compile(r"\barea:\s*([^,\n]+)")
MODE_IDS = ("readonly", "plan", "writable")


def registered_i18n_keys() -> set[str]:
    """The keys of the `en` bundle the plugin registers with ctx.i18n.register."""
    return set(re.findall(r"([A-Za-z0-9_]+):", SOURCE.split("en: {", 1)[1].split("}", 1)[0]))


class TestSdkImports(unittest.TestCase):
    def test_every_imported_identifier_is_a_real_sdk_export(self):
        if SDK_BARREL is None:
            self.skipTest("desktop SDK sources not found (set HERMES_REPO to point at a checkout)")
        barrel = SDK_BARREL.read_text(encoding="utf-8")
        match = SDK_IMPORT_RE.search(SOURCE)
        if match is None:
            self.fail("no '@hermes/plugin-sdk' import found in the desktop half")
        imported = [
            name.strip().split(" as ")[0].strip()
            for name in match.group(1).split(",")
            if name.strip()
        ]
        self.assertTrue(imported, "the desktop half imports nothing from the SDK?")
        missing = [name for name in imported if not re.search(rf"\b{re.escape(name)}\b", barrel)]
        self.assertEqual(missing, [], "imported from the plugin SDK but not exported by it")


class TestContributionAreas(unittest.TestCase):
    def test_every_area_id_comes_from_an_sdk_constant(self):
        """A literal area id is how a contribution silently never renders.

        The palette's real area id is the SDK's PALETTE_AREA ('palette'), not the string
        'PALETTE_AREA'; registering into the literal reads correctly and shows nothing.
        """
        values = [value.strip() for value in AREA_RE.findall(SOURCE)]
        self.assertEqual(
            len(values), 2,
            f"expected 2 registration sites (the status-bar control + the palette loop); "
            f"update this count if you add one: {values}",
        )
        quoted = [value for value in values if value[0] in "'\""]
        self.assertEqual(quoted, [], "area ids must be imported constants, not string literals")

    def test_the_palette_constant_is_imported_and_used(self):
        self.assertIn("PALETTE_AREA", SOURCE)


class TestI18nKeys(unittest.TestCase):
    def test_every_mode_has_a_label_and_a_tooltip(self):
        registered = registered_i18n_keys()
        for mode in MODE_IDS:
            self.assertIn(f"mode_{mode}", registered)
            self.assertIn(f"tip_{mode}", registered)

    def test_the_loading_and_error_copy_is_registered(self):
        registered = registered_i18n_keys()
        self.assertIn("unavailable", registered, "the tooltip shown when the fetch failed")
        self.assertIn("loading", registered, "the tooltip shown before the first fetch resolves")


class TestSessionScope(unittest.TestCase):
    """The chip must speak about a SESSION, and name the draft case explicitly.

    A chip that read the machine default and silently wrote it would look identical and
    be wrong: this is the whole point of the change.
    """

    def test_the_chip_reads_the_focused_stored_session_id(self):
        self.assertIn("focusedStoredSessionId", SOURCE)
        self.assertIn("useValue", SOURCE)

    def test_a_session_request_carries_the_session(self):
        self.assertIn("?session=", SOURCE)
        self.assertIn("body = session ?", SOURCE)

    def test_the_writable_pill_counts_down_and_never_resizes(self):
        """Three separate ways this can twitch, pinned one by one.

        Proportional digits change width as they tick; a shorter number changes width when
        the digits drop; and a countdown that only appears while active resizes the whole
        track on click. The slot is always rendered when the feature is on, so the pill's
        width is a function of the setting, not of the mode or the minute.
        """
        self.assertIn("expiry_minutes", SOURCE)          # the payload field it reads
        self.assertIn("tabular-nums", SOURCE)            # digits share one width
        self.assertIn("minWidth", SOURCE)                # the slot is a fixed box
        self.assertIn("mode === 'writable' && left !== null", SOURCE)

    def test_no_minutes_when_the_setting_is_off(self):
        """`writable_expiry_minutes: 0` must render the plain label, not an empty slot."""
        self.assertIn("counting ? jsx(", SOURCE)

    def test_the_chip_reads_the_writable_countdown(self):
        """A countdown the chip ignores is a limit the user cannot see coming."""
        self.assertIn("expires_in", SOURCE)

    def test_the_draft_case_is_labelled_as_the_new_sessions_default(self):
        keys = registered_i18n_keys()
        self.assertIn("tip_draft", keys)
        self.assertIn("NEW sessions", SOURCE)


#: The mode id -> fill/text pairs, as they appear in desktop/plugin.js.
TONES_RE = re.compile(r"(\w+): *\{ *bg: *'(#[0-9a-fA-F]{6})', *fg: *'(#[0-9a-fA-F]{6})' *\}")


def tones() -> dict[str, tuple[str, str]]:
    """{mode: (bg, fg)} from the plugin's TONES map."""
    return {m.group(1): (m.group(2), m.group(3)) for m in TONES_RE.finditer(SOURCE)}


def _luminance(colour: str) -> float:
    """WCAG relative luminance of a '#rrggbb' string."""
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]

    def linear(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two '#rrggbb' colours."""
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class TestModeColours(unittest.TestCase):
    """The active pill's colour is the mode's identity: green = safe, yellow = caution,
    red = nothing is blocked. Decoration only, but it must stay readable."""

    def test_every_mode_has_a_tone(self):
        self.assertEqual(set(tones()), set(MODE_IDS))

    def test_the_tone_text_is_readable_on_its_fill(self):
        for mode, (bg, fg) in tones().items():
            ratio = contrast(fg, bg)
            self.assertGreaterEqual(
                round(ratio, 2), 4.5, f"{mode}: {fg} on {bg} is only {ratio:.2f}:1"
            )

    def test_the_agreed_colours_are_the_ones_shipped(self):
        # Pinned on purpose: a palette tweak should be a deliberate edit here too, and a
        # contrast-only test would happily accept three shades of grey.
        self.assertEqual(
            tones(),
            {
                "readonly": ("#15803d", "#ffffff"),
                "plan": ("#facc15", "#1c1917"),
                "writable": ("#b91c1c", "#ffffff"),
            },
        )

    def test_the_fill_is_gated_on_the_active_button(self):
        """A pill on the wrong button is the whole bug this change could introduce."""
        match = SDK_IMPORT_RE.search(SOURCE)
        imported = [n.strip().split(" as ")[0].strip() for n in match.group(1).split(",") if n.strip()]
        self.assertNotIn(
            "SegmentedControl", imported,
            "SegmentedControl has no per-option colour hook; using it silently drops the colours",
        )
        self.assertIn("'aria-pressed': active", SOURCE)
        self.assertIn("background: active ?", SOURCE)


if __name__ == "__main__":
    unittest.main()
