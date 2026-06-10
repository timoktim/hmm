# Stage03R Final-Gate Timeout Hardening Report

index_id: STAGE03R-MAINT-WP1-v1

branch: `stage03r/maint-final-gate-timeout-hardening`

status: pass

## Summary

This maintenance package moves the Stage03R final-gate shell-chain test out of
the default not-slow suite while preserving explicit slow/integration coverage.
It also switches pytest-timeout to signal mode, reduces duplicated final-gate
gate execution, and standardizes Stage03 / Stage03R script interpreter
selection so `.venv` is preferred when explicit environment variables are not
set.

## Files Changed

- `pyproject.toml`
- `src/evaluation/stage03r_final_gate.py`
- `tests/test_stage03r_final_gate.py`
- `scripts/check_no_private_paths.sh`
- `scripts/stage03_preflight_gate.sh`
- `scripts/stage03_preflight_smoke.sh`
- `scripts/stage03r_data_quality_ci_gate.sh`
- `scripts/stage03r_exit_target_gate.sh`
- `scripts/stage03r_final_gate.sh`
- `scripts/validate_stage01_no_private_db.sh`
- `reports/stage03r/final_gate_timeout_hardening_report.md`
- `reports/stage03r/final_gate_timeout_hardening_report.json`

## Test Selection

slow marker added: yes

per-test timeout added: yes, `@pytest.mark.timeout(600)`

timeout method before: `thread`

timeout method after: `signal`

`tests/test_stage03r_final_gate.py::test_gate_script_prints_stable_final_line`
is now marked slow and is deselected from:

```text
pytest -q tests/test_stage03r_final_gate.py -m "not slow"
pytest -q -m "not slow"
```

It can still be run deliberately with:

```text
pytest -q tests/test_stage03r_final_gate.py::test_gate_script_prints_stable_final_line -m slow
```

## Final-Gate De-Duplication

final gate de-duplicated: yes

`src/evaluation/stage03r_final_gate.py::_run_required_gates` now directly runs
only:

```text
scripts/stage03r_exit_target_gate.sh
scripts/stage03_preflight_gate.sh
```

When `stage03_preflight_gate` passes, the final-gate summary records these
covered statuses:

```text
data_quality_ci_gate: covered_by_stage03_preflight_gate
private_data_hygiene: covered_by_stage03_preflight_gate
stage01_no_private_db: covered_by_stage03_preflight_gate
```

Missing or failing preflight still blocks the final gate.

## Interpreter Selection

interpreter selection standardized: yes

Audited and updated:

- `scripts/stage03r_exit_target_gate.sh`
- `scripts/stage03r_data_quality_ci_gate.sh`
- `scripts/stage03_preflight_gate.sh`
- `scripts/stage03_preflight_smoke.sh`
- `scripts/validate_stage01_no_private_db.sh`
- `scripts/check_no_private_paths.sh`
- `scripts/stage03r_final_gate.sh`

Python precedence:

```text
PYTHON_BIN / PYTHON when supported
.venv/bin/python
PATH python
PATH python3
```

Pytest precedence:

```text
PYTEST_BIN / PYTEST when supported
.venv/bin/pytest
PATH pytest
```

## Commands Run

- `.venv/bin/python -m compileall -q src tests`
  - result: pass
- `.venv/bin/pytest -q tests/test_stage03r_final_gate.py -m "not slow"`
  - result: pass, `15 passed, 1 deselected in 0.07s`
- `.venv/bin/pytest -q tests/test_stage03r_final_gate.py::test_gate_script_prints_stable_final_line -m slow`
  - result: pass, `1 passed in 81.71s`
- `.venv/bin/pytest -q -m "not slow"`
  - result: pass, `719 passed, 2 skipped, 3 deselected, 27 warnings in 160.51s`

not-slow result: pass

explicit slow final-gate script test result: pass

## Boundary Flags

```text
external data fetch: no
private DB required: no
model training: no
final holdout consumed: no
HMM/HSMM training modified: no
trading, sizing, buy/sell, or decision output: no
```

## Remaining Risks

- The explicit slow final-gate script test remains integration-style and took
  81.71 seconds locally.
- Existing gate scripts may still rewrite committed Stage03R report artifacts
  when run with the local DB present; test side effects were restored before
  committing this maintenance package.
