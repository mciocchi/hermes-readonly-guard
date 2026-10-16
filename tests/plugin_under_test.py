"""Load the readonly-guard package by path, for tests.

The plugin directory name carries a hyphen, so it is not importable by name.
``importlib`` with ``submodule_search_locations`` yields a real package, which
makes the plugin's own relative imports (``from .state import ...``) resolve.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
_MODULE_NAME = "readonly_guard_under_test"


def load_plugin():
    """The plugin package, loaded once per process."""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME,
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def load_state():
    """The plugin's ``state`` submodule (same module object the package holds)."""
    load_plugin()
    return importlib.import_module(f"{_MODULE_NAME}.state")


def accepts_var_kwargs(callback) -> bool:
    """True when *callback* takes ``**kwargs`` — the runtime's forward-compat contract."""
    return any(
        param.kind is inspect.Parameter.VAR_KEYWORD
        for param in inspect.signature(callback).parameters.values()
    )
