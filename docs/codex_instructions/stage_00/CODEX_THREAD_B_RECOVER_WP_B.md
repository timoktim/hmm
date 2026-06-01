# CODEX_THREAD_B_RECOVER_WP_B

Repository: timoktim/hmm
Assigned index_id: STAGE00-WP-B-v1
Work package: docs/work_packages/stage_00/STAGE00_WP_B_baseline_freeze.md

## Situation

The GitHub `main` branch did not initially contain the V0 source. The V0 baseline source currently exists in PR #1 / branch:

```text
stage00/wp-a-evidence-registry
```

PR #1 imports the V0 baseline source and implements WP-A. Until PR #1 is merged, `main` is not a valid starting point for WP-B implementation.

## Correct starting point

Preferred path:

1. Wait until PR #1 is merged into `main`.
2. Start a new branch from updated `main`:

```text
stage00/wp-b-baseline-freeze
```

3. Execute only:

```text
docs/work_packages/stage_00/STAGE00_WP_B_baseline_freeze.md
```

Temporary stacked path if asked to proceed before PR #1 merges:

1. Branch from `stage00/wp-a-evidence-registry`, not from old `main`.
2. Name branch:

```text
stage00/wp-b-baseline-freeze-stacked-on-wp-a
```

3. Clearly state in the PR body that it is stacked on PR #1 and must be rebased after PR #1 is merged.

## Scope

WP-B must implement baseline freeze only:

- `src/evaluation/baseline_freeze.py`
- `src/evaluation/baseline_collectors.py` if needed
- `tests/test_baseline_freeze.py`
- `reports/baseline_freeze/stage00_v0_baseline_20260601/*`

Do not modify HMM/HSMM training algorithms. Do not implement WP-C UI readiness policy. Do not fetch new data.

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_baseline_freeze.py
pytest -q -m "not slow"
python -m src.evaluation.baseline_freeze --db data/db/a_share_hmm.duckdb --output reports/baseline_freeze/stage00_v0_baseline_20260601 --run-tests no --no-fetch --register-evidence
```

If the local DB is unavailable, still generate:

```text
reports/baseline_freeze/stage00_v0_baseline_20260601/summary.md
reports/baseline_freeze/stage00_v0_baseline_20260601/baseline_snapshot.json
reports/baseline_freeze/stage00_v0_baseline_20260601/missing_artifacts.md
```

and mark `db_available=false`.

## Required content in summary

The summary must explicitly state:

- HMM is causal nowcast / state context / weak auxiliary signal, not standalone trading decision engine.
- HSMM lifecycle allows state age and state phase display.
- HSMM low/medium/high exit tendency is internal diagnostic only.
- HSMM numeric `p_exit` is hidden unless usable_probability/readiness passes.
- next-state tendency is realized historical tendency, not predicted probability.
- No external data was fetched.

## Return format

```text
Thread: B
index_id: STAGE00-WP-B-v1
starting point used: updated main / stacked on stage00/wp-a-evidence-registry
branch: ...
PR: ...
status: pass / partial / fail
commands run:
- ...
results:
- ...
generated reports:
- ...
DB found: yes/no
external data fetch: no
training algorithm modified: no
WP-C UI readiness implemented: no
risks:
- ...
```
