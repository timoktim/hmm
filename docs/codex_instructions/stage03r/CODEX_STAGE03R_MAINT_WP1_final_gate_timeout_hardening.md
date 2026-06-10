# CODEX_STAGE03R_MAINT_WP1_final_gate_timeout_hardening

Repository: timoktim/hmm

Index id: `STAGE03R-MAINT-WP1-v1`

Work package: `docs/work_packages/stage03r/STAGE03R_MAINT_WP1_final_gate_timeout_hardening.md`

Suggested branch: `stage03r/maint-final-gate-timeout-hardening`

## Instruction

Start from updated `main`. Create the suggested branch and execute only `STAGE03R-MAINT-WP1-v1`.

This is a Stage03R maintenance package. It is not part of Stage03V implementation and must not alter Stage03V contracts or Stage03V runtime work.

The goal is to stop `pytest -q -m "not slow"` from timing out on the end-to-end Stage03R final-gate shell-chain test while preserving explicit final-gate coverage for slow/integration runs.

## Context

During Stage03V WP0 validation, WP0-specific tests passed, but the broader not-slow suite timed out in:

```text
tests/test_stage03r_final_gate.py::test_gate_script_prints_stable_final_line
scripts/stage03r_final_gate.sh
```

This test is an end-to-end integration script check. It should not live in the not-slow suite.

Also inspect interpreter selection in Stage03 / Stage03R gate scripts. Some scripts prefer PATH `python` / `pytest` before `.venv`, which can make standalone gate runs use the wrong interpreter.

## Required work

1. Mark the final-gate shell-chain test as slow.

In `tests/test_stage03r_final_gate.py`, add `import pytest` if absent and mark:

```python
@pytest.mark.slow
@pytest.mark.timeout(600)
def test_gate_script_prints_stable_final_line() -> None:
    ...
```

If per-test timeout is unavailable, keep `@pytest.mark.slow` and document why timeout was not added.

2. Change pytest timeout method to signal if safe.

In `pyproject.toml`, change:

```toml
timeout_method = "thread"
```

to:

```toml
timeout_method = "signal"
```

If local or CI behavior rejects signal-based timeout, document the reason and use the safest available setting.

3. Reduce duplicated final-gate work.

`stage03_preflight_gate.sh` already calls:

```text
scripts/check_no_private_paths.sh
scripts/validate_stage01_no_private_db.sh
scripts/stage03r_data_quality_ci_gate.sh
```

`src/evaluation/stage03r_final_gate.py::_run_required_gates` currently runs those directly and also calls `stage03_preflight_gate.sh`. Refactor so final-gate script execution runs only the non-covered high-level gates, at minimum:

```text
scripts/stage03r_exit_target_gate.sh
scripts/stage03_preflight_gate.sh
```

Preserve final-gate strictness. Missing or failing preflight must still block. The final-gate summary must still indicate private path hygiene, Stage01 no-private-DB validation, and data-quality CI are covered by preflight. A covered status such as `source: covered_by_stage03_preflight_gate` is acceptable.

4. Standardize interpreter selection.

For Stage03 / Stage03R shell scripts defining `choose_python` or `choose_pytest`, use this precedence:

```text
PYTHON_BIN / PYTEST_BIN if set
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

Do not break exported `PYTHON_BIN` and `PYTEST_BIN` behavior from `scripts/stage03r_final_gate.sh`.

5. Add a maintenance report.

Create:

```text
reports/stage03r/final_gate_timeout_hardening_report.md
reports/stage03r/final_gate_timeout_hardening_report.json
```

Report must include:

```text
index id
branch
files changed
slow marker added
per-test timeout added
timeout method before / after
final gate de-duplication summary
interpreter-selection scripts audited
commands run
not-slow result
explicit slow final-gate script test result
external data fetch: no
private DB required: no
model training: no
final holdout consumed: no
```

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03r_final_gate.py -m "not slow"
pytest -q tests/test_stage03r_final_gate.py::test_gate_script_prints_stable_final_line -m slow
pytest -q -m "not slow"
git diff --check
```

If the explicit slow final-gate script test is too slow locally, document it as a slow-test concern. The key requirement is that `pytest -q -m "not slow"` no longer invokes or times out on that shell-chain test.

## Forbidden behavior

Do not weaken final-gate verdict semantics.

Do not remove the ability to run `scripts/stage03r_final_gate.sh` explicitly.

Do not skip final-gate validation entirely.

Do not modify Stage03V contracts or Stage03V runtime work.

Do not fetch external data.

Do not require private DuckDB availability in CI.

Do not retrain HMM / HSMM models.

Do not consume any final holdout.

Do not create trading, sizing, buy/sell, or decision outputs.

## Return format

Use the work package return contract exactly:

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
