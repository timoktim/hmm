# CI Validation Policy

Index ID: STAGE02-WP-B-v1

## Purpose

The repository must have a CI path that runs on GitHub without the private V0 DuckDB. CI validates importability, unit-level diagnostic behavior, UI readiness policy boundaries, and private path hygiene. It does not generate data-backed Stage 01 reports.

## CI-safe scope

The GitHub Actions workflow runs:

- `python -m compileall -q src tests`
- `pytest -q tests/test_hmm_confidence.py tests/test_hmm_label_alignment.py tests/test_hmm_churn_dwell.py`
- `pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py`
- `pytest -q tests/test_private_path_hygiene.py`
- `bash scripts/check_no_private_paths.sh`
- `bash scripts/validate_stage01_no_private_db.sh`

The workflow must not require `data/db/a_share_hmm.duckdb`, must not set `ASHARE_HMM_DB_PATH`, and must not fetch market or constituent data.

## Boundaries

- Private DuckDB required: no
- External data fetch: no
- HMM/HSMM training algorithm changes: no
- Stage 01 diagnostic algorithm changes: no
- DuckDB/WAL committed: no

## Failure behavior

CI failure should be treated as validation evidence failure, not as a reason to fetch data. If a data-backed report is needed, run that validation locally under `docs/runtime/LOCAL_DB_HANDOFF.md` and record it as a separate local artifact.
