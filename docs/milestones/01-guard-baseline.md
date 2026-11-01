---
schema: milestone/1
architecture: 1
mvp: true
satisfies: [I1, I2, I3, I4, I5, I6, I9]
---

# 01: The guard as shipped

**Goal.** A user can put one session into read-only, plan or writable and watch the guard hold that session to it, with `writable` ending on its own lease.

**Exit.** `python -m unittest discover -s tests -t tests` — 199 tests, `OK`.

**Out of scope.** Keybinds, catalog listing, Windows CI (all delivered before this document existed; the suite is what ratifies them).

## Features

F1: a user can stop an agent from writing anything in the current chat
F2: a user can let an agent plan, with only the plan markdown writable
F3: a user can grant full access for a bounded time, and it expires on its own
F4: a user can keep two chats in different modes at once
F5: a user can find out which mode is enforced, from the chip, `/readonly status`, or the API

## Tickets

### T007: The dashboard reports the configured default, not a constant

```ticket
id: T007
feature: F5
priority: P0
order: 1
effort: 2
status: todo
depends_on: []
files: [dashboard/plugin_api.py, tests/test_dashboard_api.py]
gate: python -m unittest discover -s tests -t tests -p "test_dashboard_api.py"
```

**Context.** Architecture 2 §3 (the HTTP contract: `GET /state` reports
`{mode, default, expiry_minutes, session, modes, source}`, and an absent `session` means the
default that new sessions start with) and §4 invariant I5 (the mode enforced for a session equals
the mode `GET /state` reports for it). This is F5 failing: the chip tells the user read-only while
the guard enforces plan.

The dashboard half imports `settings` as a *top-level* module — `sys.path.insert(0, _PLUGIN_DIR)`
then `from settings import default_mode, writable_expiry_minutes`
(`dashboard/plugin_api.py:29-34`) — while the only `set_reader(ctx.get_config)` call is
`__init__.py:334`, on the *package-relative* module. Hermes loads the agent half as a package
(`spec_from_file_location(..., submodule_search_locations=...)`,
`hermes_cli/plugins_loader.py:718-719`), so those are two different module objects and the
dashboard half's `_reader` is permanently `None`. `default_mode()` (`settings.py:49-53`) then falls
back to `DEFAULT_MODE`, the constant `readonly`, whatever `config.yaml` says.
`writable_expiry_minutes()` is blind the same way and reports 30.

So with `default_mode: plan`, a session with no entry is enforced as plan while `GET /state`
answers `readonly`: the chip lights read-only through turns that are all planned, and a user who
clicks it is operating on a state that disagrees with what is enforced. The write path is honest —
a session-less `POST /state` goes through `save_plugin_settings` — which is how the setting was
changed from a control that then misreported it.

Bind the reader where the dashboard half imports it (`set_reader` on that module), and let
`settings.py` keep the only copy of the validation: a malformed value must still read as
`readonly`, not as whatever the file happened to contain. Import Hermes' config loader lazily,
the way `_write_setting` already imports its writer (`dashboard/plugin_api.py:47-56`), so a bare
test interpreter still imports the module. `plugin.yaml` gains no key. Run the gate under an
interpreter that has `fastapi`: the test module raises `SkipTest` when it does not, and a skip is
not a pass.

**Acceptance**

A1. With `plugins.entries.readonly-guard.settings.default_mode: plan` in a temp `HERMES_HOME` config, `GET /state` with no session returns `mode: plan`, `default: plan`, `source: default`.
A2. Under that same config, `GET /state?session=<an id with no entry>` returns `mode: plan` — the chip's case for a chat that has never been switched.
A3. With `writable_expiry_minutes: 0` in that config, the payload's `expiry_minutes` is `0` and a writable session's `expires_in` is null.
A4. With no Hermes on `sys.path`, the module still imports and reports `readonly` and 30 — the fail-closed fallback, unchanged.
A5. For a session with no entry, the mode `GET /state` reports equals the mode the guard's `resolve_mode` returns under the same config (I5), asserted in one test holding both halves.

**Test plan**

- `tests/test_dashboard_api.py::test_get_without_a_session_reports_the_configured_default` fails first: it expects `plan` and gets the constant `readonly`.
- `tests/test_dashboard_api.py::test_get_for_a_session_with_no_entry_reports_the_configured_default` fails first, for the same reason and on the chip's own path.
- `tests/test_dashboard_api.py::test_a_configured_zero_expiry_is_reported` fails first: 30 is reported instead of 0.
- `tests/test_dashboard_api.py::test_the_reported_default_matches_the_mode_the_guard_enforces` fails first.
- `tests/test_dashboard_api.py::test_the_module_imports_without_hermes_on_the_path` is a pin, green before the change: the lazy import must not turn an absent Hermes into an import error.
