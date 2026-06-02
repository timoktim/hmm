# STAGE02_WP_B_ci_validation_artifact_skeleton

Stage: 02 / Causal evidence and reproducible validation gates
Work package: WP-B
Index ID: STAGE02-WP-B-v1
Executor: Codex B
Recommended branch: `stage02/wp-b-ci-validation-artifacts`

## Objective

Stage 01 was validated with a local V0 DuckDB but has no GitHub Actions CI. This package creates a CI-safe validation skeleton that proves core modules compile and behave correctly without private DB data, while also defining how local DB-backed artifacts are recorded.

Goal: add reproducible CI and artifact conventions without committing private DB, without fetching data, and without changing model algorithms.

## Starting point

Start from updated `main`.

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage02/wp-b-ci-validation-artifacts
```

Read first:

```text
docs/runtime/LOCAL_DB_HANDOFF.md
docs/acceptance/stage_01/STAGE01_FINAL_INTEGRATION_SUMMARY.md
docs/acceptance/stage_01/STAGE01_HARD_ISSUE_REVIEW.md
```

## Scope

Allowed additions:

```text
.github/workflows/ci.yml
scripts/validate_stage01_no_private_db.sh
scripts/check_no_private_paths.sh
docs/validation/CI_VALIDATION_POLICY.md
docs/validation/LOCAL_DB_ARTIFACT_POLICY.md
reports/ci_validation/stage02_wp_b_ci_validation_summary.md
reports/ci_validation/stage02_wp_b_ci_validation_summary.json
tests/test_private_path_hygiene.py
```

Allowed small updates:

```text
.gitignore
pyproject.toml
```

Only if required for test discovery or report allowlisting.

Do not modify:

```text
src/models/
src/features/
src/evaluation/hmm_confidence.py
src/evaluation/hmm_label_alignment.py
src/evaluation/hmm_churn_dwell.py
```

## CI requirements

Add GitHub Actions workflow that runs without private DB:

```text
python -m compileall -q src tests
pytest -q tests/test_hmm_confidence.py tests/test_hmm_label_alignment.py tests/test_hmm_churn_dwell.py
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
pytest -q tests/test_private_path_hygiene.py
```

Optional if runtime permits:

```text
pytest -q -m "not slow"
```

CI must not require `data/db/a_share_hmm.duckdb`.

CI must not fetch external market/constituent data.

## Private path hygiene

Add a test or script that fails if committed docs/reports contain local absolute paths such as:

```text
/Users/
/Volumes/
/home/
.codex_worktrees
HMM高阶分析器
*.duckdb absolute path strings
```

The check should avoid false positives for policy examples that intentionally mention generic paths like `/absolute/path/to/a_share_hmm.duckdb`.

At minimum scan:

```text
docs/
reports/
```

## Local DB artifact policy

Create docs explaining:

- DuckDB is never committed;
- local DB-backed validation must record canonical path or redacted path only;
- reports must include `external data fetch: no`;
- reports must include `DuckDB committed: no`;
- local DB path can be supplied by `ASHARE_HMM_DB_PATH`;
- full private absolute paths are forbidden in committed docs/reports.

## Required commands

Run locally:

```bash
python -m compileall -q src tests
pytest -q tests/test_private_path_hygiene.py
pytest -q tests/test_hmm_confidence.py tests/test_hmm_label_alignment.py tests/test_hmm_churn_dwell.py
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

If `python` is unavailable, use `.venv/bin/python` and document it.

## Acceptance criteria

Pass if:

- CI workflow exists and does not require private DB;
- private path hygiene test/script works;
- documentation explains local DB artifact policy;
- no external data fetch;
- no training algorithm change;
- no DuckDB/WAL committed;
- report summary generated under `reports/ci_validation/`.

## Return format

```text
WP: STAGE02-WP-B-v1
status: pass / partial / fail
branch: stage02/wp-b-ci-validation-artifacts
PR: ...
commands run:
- ...
CI:
- workflow file: ...
- private DB required: no
private path hygiene:
- script: pass/fail
- pytest: pass/fail
local DB artifact policy:
- docs created: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```
