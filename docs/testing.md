# Testing conventions

This repository uses Python 3.11 and **pytest** in CI. Existing `unittest.TestCase` tests remain supported.
Tests must be deterministic, hermetic, and runnable without a charger, network,
root privileges, installed systemd services, or developer credentials.

## Run tests

```sh
python3 -m pip install 'pytest>=8,<10'
python3 -m pytest tests -v --durations=0 --durations-min=0
```

The legacy `python3 -m unittest discover -s tests -v` command remains supported.

Before a structural refactor, record the baseline with:

```sh
python3 -m unittest discover -s tests -v 2>&1 | tee /tmp/gway-remote-tests-before.log
```

Record discovered test count, test identifiers, failures, and wall-clock duration.
After moving files, compare identifiers and counts, not just the exit status.
Do not treat skipped or undiscovered tests as successful coverage.

## Naming and organization

- Name files `test_<subsystem>_<behavior>.py` when a single subsystem needs
  multiple modules. Existing names need not be changed solely for aesthetics.
- Use `TestCase` classes grouped by public behavior and methods beginning
  `test_`. A test name should describe a condition and expected result.
- Keep transport/API tests separate from command-dispatch contract tests.
- Prefer one subsystem per module; use subtests for a compact matrix of the
  same behavior, not for unrelated scenarios.
- Future subsystem directories must include `__init__.py` so standard-library
  discovery works consistently.

## Contracts and assertions

- Test observable outcomes, durable state, and security boundaries rather
  than private implementation steps when possible.
- Maintain one authoritative explicit allowlist test for the complete mobile
  command catalog. Other tests should assert only the commands they exercise.
- Never derive an expected security allowlist from the implementation under
  test. Keep forbidden commands and argument rejection independently asserted.
- Assert failure modes and non-effects (no execution, no writes, no leaks),
  not merely exception types or success-path values.
- Do not weaken assertions or remove tests to make CI green.

## Isolation and fixtures

- Use `tempfile.TemporaryDirectory` for files and SQLite databases; close
  handles and register cleanup immediately with `addCleanup` or context managers.
- Use `unittest.mock.patch` at the lookup site for time, subprocess, filesystem
  paths, GitHub clients, sockets, and service interactions.
- Use loopback ephemeral ports for in-process HTTP tests; always shut down
  servers and join threads. Never contact a real external endpoint.
- Restore environment variables and module globals after each test.
- Use fake clocks or controlled events instead of arbitrary sleeps.
- Share small fixtures through `tests/support` only when duplication warrants
  it; avoid a large fixture framework or shared mutable global fixtures.
- No tests may deploy, restart services, run Codex, use production databases,
  or perform privileged writes.

## Layers and CI

- **Unit:** pure behavior, mocked I/O, no external dependencies.
- **Contract:** stable CLI/API payloads, authorization, admission and explicit
  allowlists; local-only.
- **Integration:** multiple in-process components using isolated temporary
  resources; no real infrastructure.
- **Field validation:** explicit operator-authorized issues, never CI.

Keep the single local discovery command working while organizing tests.
CI runs pytest in one matrix job per subsystem and in the separate validation job.\nRun `python3 -m pytest tests -v --durations=0 --durations-min=0` for\nper-test timings locally. The optional `python3 -m tests.support.run_tests --group all`\nrunner remains available for unittest-compatible timing output.\nStructural checks live in `tests/support/test_architecture.py`.\nChanges to the suite must preserve all existing test coverage unless a
specific obsolete test is removed with a documented replacement.

## Refactor sequence

1. TR1: document conventions and preserve baseline.
2. TR2: reorganize modules without changing test semantics.
3. TR3: consolidate fixtures and duplicated contracts.
4. TR4: strengthen behavioral, failure and security assertions.
5. TR5: add CI groups, timings and architecture enforcement.

TR1 deliberately makes no runtime, test or workflow changes.
