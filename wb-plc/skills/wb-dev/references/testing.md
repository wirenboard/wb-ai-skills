# Testing WB Python services

How tests are organized in Wiren Board Python projects. The service template
(`wb-python-service-template`) does not ship tests — the patterns below are distilled from
production repos: `wb-cloud-agent`, `wb-nm-helper`, `wb-diag-collect`, `wb-ai-skills`.
Process rules (what must be tested before a PR) live in the `wb-git`/`wb-development` skills;
this is the engineering how-to.

## Layout

```
tests/
├── __init__.py          ← required: pybuild discovers the suite by package
├── conftest.py          ← shared fixtures for the whole suite
├── data/                ← captured real-world inputs + expected outputs
│   ├── wb-mqtt-serial.conf
│   └── wb-mqtt-serial.conf.filtered   ← golden file: expected result next to input
└── test_<module>.py     ← one file per production module
```

- `tests/` sits at the repo root, next to the production package.
- One `test_<module>.py` per production module (`wb-nm-helper`: `test_connection_checker.py`,
  `test_dns_resolver.py`, ...). Plain pytest functions, no test classes.
- `tests/data/` holds **captured artefacts from real controllers** (configs, RPC responses,
  `/proc` contents) — not hand-invented minimal samples. Expected outputs live next to inputs
  as golden files (`wb-diag-collect`: `20bridge.conf` → `20bridge.conf.filtered`).

## Test style

Black-box through the public API: call the function, assert the returned value or the raised
exception — not internal call sequences (same principle as `fw-unittests` for firmware).

```python
def test_do_curl_success_response(settings, mock_subprocess):
    mock_subprocess(status.OK, '{"result": "success"}')
    data, code = do_curl(settings)
    assert data == {"result": "success"}
    assert code == 200

def test_do_curl_invalid_method(settings):
    with pytest.raises(ValueError, match="Invalid method"):
        do_curl(settings, method="invalid")
```

## Fixtures — the WB patterns

Everything at the process boundary is mocked; tests never touch a real broker, network,
hardware, or systemd.

| Pattern | What it solves | Example |
|---|---|---|
| **Factory fixture** | One fixture builds parameterized mocks | `shell_returning(rc, stdout, stderr)` returns a configured `MagicMock` (`wb-ai-skills`) |
| **Fake sysroot in `tmp_path`** | Code reads controller paths (`/etc/wb-release`, `/proc/uptime`) | fixture copies captured files from `tests/data/` into `tmp_path` mirroring the real layout, code gets the root injected (`wb-ai-skills` `controller_root`) |
| **`autouse` state reset** | Module-level state leaks between tests | clear module dicts/threads before and after each test (`wb-cloud-agent` `_clear_metrics_monitor_state`) |
| **`patch` at the boundary** | subprocess / curl / MQTT client / file paths | `patch("...METRICS_COLLECTOR_TEMPLATE_PATH", str(tmp_file))`, `patch` on `subprocess.run` (`wb-cloud-agent`) |
| **`monkeypatch` for CLI args** | Testing `main()` entry points | `monkeypatch.setattr(sys, "argv", [...])` (`wb-cloud-agent` `set_argv`) |

Shared settings objects come from a `settings` fixture constructing the service's real config
class with test values — not a dict imitation.

## Running

| Where | How |
|---|---|
| Locally (devenv/venv) | `pytest`; with coverage — commands from `codestyle/python.ru.md` (`pytest --cov --cov-config=.coveragerc --cov-fail-under=<N>`) |
| During .deb build | pybuild runs the suite automatically (`tests/` is a package); for coverage inside `wbdev ndeb`/`cdeb`: `export WBDEV_PYBUILD_TEST_ARGS="--cov ... --cov-fail-under=<N>"` |
| CI (Jenkins) | flags in the one-line Jenkinsfile, e.g. `buildDebSbuild defaultRunPythonChecks: true, defaultAngryPylint: true, defaultRunCoverage: true, defaultCoverageMin: "59", defaultDoCoverallsReporting: true` |

- `defaultCoverageMin` is per-repo (`wb-cloud-agent`: 59, `wb-nm-helper`: 80) — when adding
  tests to an existing repo, don't lower it; when bootstrapping, set a reachable floor and
  raise it as coverage grows.
- Every Python repo carries `tests/test_version.py` (from `package-bootstrap`) locking
  `debian/changelog` ↔ `pyproject.toml` ↔ `__init__.py` — don't remove it, it fails the build
  on version drift.

## What NOT to do

- **No real I/O in unit tests** — no live MQTT broker, no network, no SSH to a controller.
  Integration tests against real hardware are a separate story (custom Jenkinsfile, see
  `package-bootstrap` "When to ask the user").
- **Don't edit a failing test to make it pass** — surface it; the user decides whether the
  test or the production code is wrong (per `wb-development` coder rules).
- **Don't hand-invent fixture data** when a real controller is available — capture the real
  config/output into `tests/data/` and cut it down.
- **Don't skip the docstring** on a non-trivial test (multi-step setup, async) — reviewers
  flag it (`code-review-orchestrator` project rules).
