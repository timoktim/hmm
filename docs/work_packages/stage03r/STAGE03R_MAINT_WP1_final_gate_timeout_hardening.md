# STAGE03R_MAINT_WP1_final_gate_timeout_hardening

Stage: Stage03R maintenance

Work package: STAGE03R-MAINT-WP1

Index id: `STAGE03R-MAINT-WP1-v1`

Suggested branch: `stage03r/maint-final-gate-timeout-hardening`

Codex instruction: `docs/codex_instructions/stage03r/CODEX_STAGE03R_MAINT_WP1_final_gate_timeout_hardening.md`

Date: 2026-06-10

## Objective

Harden the Stage03R final-gate test path so `pytest -q -m "not slow"` does not time out on an end-to-end gate script test, while preserving final-gate strictness for explicit slow/integration runs.

This package is a maintenance fix triggered by the Stage03V WP0 validation run, where the WP0-specific tests passed but the broader not-slow suite timed out inside:

```text
tests/test_stage03r_final_gate.py::test_gate_script_prints_stable_final_line
scripts/stage03r_final_gate.sh
```

## Problem statement

The final-gate script test is an end-to-end integration check. It invokes `scripts/stage03r_final_gate.sh`, which in turn may invoke multiple gate scripts. Several of those gates already have focused unit tests or are included in Stage03 preflight. Keeping this full chain in the not-slow suite creates little incremental coverage and can cause avoidable timeouts.

There is also an interpreter-selection inconsistency in some gate scripts: some `choose_python` / `choose_pytest` functions prefer PATH executables before `.venv`, so standalone script runs can use system pytest or python while the project dependencies live in `.venv`. The final-gate entry point exports `PYTHON_BIN`, but child scripts remain fragile when run directly.

## Scope

Allowed changes:

- Mark the Stage03R final-gate script integration test as slow.
- Optionally add a per-test timeout marker for the slow final-gate script test.
- Change pytest timeout method from `thread` to `signal` if supported by the project environment.
- Reduce duplicated work in `src/evaluation/stage03r_final_gate.py::_run_required_gates` by relying on `stage03_preflight_gate` for gates that it already runs.
- Preserve reporting of covered gate statuses so final-gate summaries remain readable.
- Standardize `choose_python` and `choose_pytest` in Stage03 / Stage03R gate scripts to prefer explicit environment variables, then `.venv`, then PATH fallbacks.
- Add tests or update existing tests to prove not-slow no longer runs the full final-gate shell chain.
- Add a short maintenance report documenting the timeout fix and residual risks.

Forbidden changes:

- Do not weaken Stage03R final-gate verdict semantics.
- Do not remove the ability to run the final-gate shell script explicitly.
- Do not skip final-gate validation entirely.
- Do not modify Stage03V contracts or Stage03V runtime code.
- Do not fetch external data.
- Do not require private DuckDB availability in CI.
- Do not retrain HMM / HSMM models.
- Do not consume any final holdout.
- Do not create trading, sizing, buy/sell, or decision outputs.

## Required implementation details

### 1. Move shell-chain test out of not-slow

In `tests/test_stage03r_final_gate.py`, add `import pytest` if absent and mark:

```python
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_gate_script_prints_stable_final_line() -> None:
    ...
```

If `pytest.mark.timeout(600)` is not available in the environment, document the reason and keep `pytest.mark.slow` as the required minimum.

### 2. Change timeout method to signal

In `pyproject.toml`, change:

```toml
timeout_method = "thread"
```

to:

```toml
timeout_method = "signal"
```

If CI or local platform rejects signal-based timeout, document the failure and use the safest available project-wide setting. Do not silently leave thread mode without explanation.

### 3. De-duplicate final-gate required gates

`stage03_preflight_gate.sh` already calls:

```text
scripts/check_no_private_paths.sh
scripts/validate_stage01_no_private_db.sh
scripts/stage03r_data_quality_ci_gate.sh
```

`src/evaluation/stage03r_final_gate.py::_run_required_gates` currently runs those gates again and then also runs `stage03_preflight_gate.sh`. This duplicates work.

Refactor so final-gate required script execution directly runs only the non-covered high-level gates, at minimum:

```text
scripts/stage03r_exit_target_gate.sh
scripts/stage03_preflight_gate.sh
```

Preserve final-gate strictness. The summary must still indicate that private path hygiene, Stage01 no-private-DB validation, and data-quality CI are covered by preflight. Acceptable implementations include:

- adding synthetic covered statuses such as `source: covered_by_stage03_preflight_gate` when preflight passes;
- or changing `_gate_status_summary` so those child gates are not separately required when `stage03_preflight_gate` passes and data-quality integration evidence says preflight includes data quality.

Do not allow a missing or failing `stage03_preflight_gate` to pass.

### 4. Standardize interpreter selection in gate scripts

For Stage03 / Stage03R shell scripts that define `choose_python` or `choose_pytest`, use this precedence:

```text
PYTHON_BIN / PYTEST_BIN if explicitly set
.venv/bin/python / .venv/bin/pytest if executable
PATH python / pytest
PATH python3 for python fallback where applicable
```

At minimum inspect and update:

```text
scripts/stage03r_exit_target_gate.sh
scripts/stage03r_data_quality_ci_gate.sh
scripts/stage03_preflight_gate.sh
scripts/stage03_preflight_smoke.sh
scripts/validate_stage01_no_private_db.sh
```

Do not break existing exported `PYTHON_BIN` and `PYTEST_BIN` behavior from `scripts/stage03r_final_gate.sh`.

### 5. Evidence report

Create:

```text
reports/stage03r/final_gate_timeout_hardening_report.md
reports/stage03r/final_gate_timeout_hardening_report.json
```

The report must include:

- index id;
- branch;
- files changed;
- whether final-gate shell-chain test is marked slow;
- whether per-test timeout exists;
- timeout method before / after;
- gate de-duplication summary;
- interpreter-selection scripts audited;
- commands run;
- not-slow result;
- slow final-gate script test result;
- external data fetch: no;
- private DB required: no;
- model training: no;
- final holdout consumed: no.

## Required tests and commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03r_final_gate.py -m "not slow"
pytest -q tests/test_stage03r_final_gate.py::test_gate_script_prints_stable_final_line -m slow
pytest -q -m "not slow"
git diff --check
```

If the explicit slow final-gate script test is too slow locally, it must be reported as a slow-test concern, but `pytest -q -m "not slow"` must pass without invoking that shell-chain test.

## Acceptance criteria

This package passes if:

- `test_gate_script_prints_stable_final_line` is excluded from `pytest -q -m "not slow"`.
- The explicit slow final-gate script test can still be run deliberately.
- `pytest -q -m "not slow"` no longer times out because of the Stage03R final-gate shell-chain test.
- Final-gate script execution still returns a stable line containing `STAGE03R_FINAL_GATE=` when run explicitly.
- Final-gate required gate execution is de-duplicated or a clear reason is documented if de-duplication is not safe.
- Gate summaries still block on missing or failed required coverage.
- Gate scripts prefer `.venv` over PATH when explicit environment variables are not set.
- Tests and reports are committed.
- No external data is fetched.
- No private DB is required.
- No HMM / HSMM training algorithm is modified.
- No final holdout is consumed.

## Return format

```text
index_id: STAGE03R-MAINT-WP1-v1
branch: stage03r/maint-final-gate-timeout-hardening
PR: ...
status: pass / partial / fail

commands run:
- ...

results:
- ...

files changed:
- ...

slow marker added: yes/no
per-test timeout added: yes/no
timeout_method: signal/thread/other
final gate de-duplicated: yes/no/partial
interpreter selection standardized: yes/no/partial
not-slow suite result: pass/fail/timeout
explicit slow final-gate script test result: pass/fail/timeout/not-run

external data fetch: no
private DB required: no
model training: no
final holdout consumed: no
HMM/HSMM training modified: no
remaining risks:
- ...
```
