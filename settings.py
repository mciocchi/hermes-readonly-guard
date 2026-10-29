"""The plugin's one setting: the mode a NEW session starts in.

Declared in ``plugin.yaml`` under ``config_schema`` — that declaration is what makes
Hermes validate the value, render a form for it in the Desktop Plugins tab, and accept
``save_plugin_settings`` writes. It lives at
``plugins.entries.readonly-guard.settings.default_mode``.

Read through the plugin context's ``get_config``, which ``register()`` injects. Without
a reader (a bare unit test, an interpreter that never called ``register``) the constant
default wins, and that default is the restrictive one: a missing setting can never
loosen the guard.
"""

from __future__ import annotations

from typing import Any, Callable

try:  # imported as part of the plugin package (agent half, tests)
    from .state import DEFAULT_MODE, MODES
except ImportError:  # imported standalone off sys.path (dashboard half)
    from state import DEFAULT_MODE, MODES

#: The key under ``plugins.entries.<id>.settings``. Also the manifest's schema key.
SETTING = "default_mode"

_reader: Callable[[str, Any], Any] | None = None


def set_reader(reader: Callable[[str, Any], Any] | None) -> None:
    """Bind the config reader — ``ctx.get_config`` in production, ``None`` to clear."""
    global _reader
    _reader = reader


#: The opt-in startup sweep. Same reader seam as ``default_mode``; declared in
#: ``plugin.yaml`` so Hermes validates and renders it.
RESET_SETTING = "reset_sessions_on_startup"


def reset_on_startup() -> bool:
    """True only when the setting is the literal boolean true.

    Deliberately strict: a quoted ``"true"``, a ``1``, or any other truthy value reads as
    off. The setting costs a user their armed modes when it fires, so it fires only on a
    value that could not have been meant as anything else — and the default is off.
    """
    raw = _reader(RESET_SETTING, False) if _reader is not None else False
    return raw is True


#: How long a writable grant survives the user's silence. 0 disables, and anything that
#: is not a non-negative int reads as the default: a typo must not quietly remove a limit.
EXPIRY_SETTING = "writable_expiry_minutes"
DEFAULT_EXPIRY_MINUTES = 30


def writable_expiry_minutes() -> int:
    """The configured TTL in minutes; ``30`` when unset, and ``0`` means never."""
    raw = _reader(EXPIRY_SETTING, DEFAULT_EXPIRY_MINUTES) if _reader is not None else DEFAULT_EXPIRY_MINUTES
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return DEFAULT_EXPIRY_MINUTES
    return raw


def default_mode() -> str:
    """The configured default mode. Anything that is not one of the three modes reads
    as :data:`DEFAULT_MODE`, so a typo in ``config.yaml`` tightens rather than loosens."""
    raw = _reader(SETTING, DEFAULT_MODE) if _reader is not None else DEFAULT_MODE
    return raw if isinstance(raw, str) and raw in MODES else DEFAULT_MODE
