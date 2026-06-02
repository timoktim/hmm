# STAGE02_WP_D_final_integration_acceptance

Stage: 02 / Causal evidence and reproducible validation gates
Work package: WP-D
Index ID: STAGE02-WP-D-v1
Executor: Codex Integration
Recommended branch: `stage02/wp-d-final-integration-acceptance`

## Objective

Close Stage 02 after WP-A, WP-B, and WP-C have been merged.

This package must produce a final Stage 02 acceptance summary and hard issue review. It must verify that Stage 02 achieved its intended goal: causal cache audit, CI-safe validation, and conservative readiness aggregation.

This package must not add model logic, train models, fetch market data, or change readiness behavior.

## Starting point

Start from updated `main` after PR #9, PR #10, and PR #11 are merged.

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage02/wp-d-final-integration-acceptance
```

Read:

```text
docs/indexes/WORK_PACKAGE_INDEX.md
docs/runtime/LOCAL_DB_HANDOFF.md
docs/acceptance/stage_01/STAGE01_FINAL_INTEGRATION_SUMMARY.md
reports/stage01_integration/stage01_integration_summary.json
reports/causal_cache/stage02_wp_a_causal_cache_audit.json
reports/ci_validation/stage02_wp_b_ci_validation_summary.json
reports/readiness_gate/stage02_wp_c_readiness_gate_report.json
```

## Allowed files

Create:

```text
docs/acceptance/stage_02/STAGE02_FINAL_INTEGRATION_SUMMARY.md
docs/acceptance/stage_02/STAGE02_HARD_ISSUE_REVIEW.md
reports/stage02_integration/stage02_integration_summary.md
reports/stage02_integration/stage02_integration_summary.json
```

Update:

```text
docs/indexes/WORK_PACKAGE_INDEX.md
```

Do not modify source code.

## Required checks

Confirm and document:

1. PR #9, PR #10, and PR #11 are merged.
2. WP-A causal cache audit exists and is machine-readable.
3. WP-B CI validation summary exists and CI-safe workflow exists.
4. WP-C readiness gate report exists and is machine-readable.
5. No Stage 02 package modified HMM/HSMM training algorithms.
6. No Stage 02 package modified `src/models/` or `src/features/` except documentation/report-only changes if any.
7. No external data fetch occurred.
8. No DuckDB or WAL file is tracked.
9. Private path hygiene remains clean.
10. Readiness remains conservative and does not become stronger than the evidence supports.

## Expected final interpretation

Current expected verdict:

```text
Stage02PassWithTrackedRisks
```

Expected tracked risks:

```text
- Causal cache rows exist but are not linked to the resolved HMM run id.
- Causal cache coverage is partial.
- Label alignment ambiguity remains high.
- CI is private-DB-free and is not a DB-backed validation artifact.
- Stage 00 registry tables are missing in the local V0 DB, so some evidence remains seed-payload-based.
```

Expected readiness conclusion:

```text
HMM output remains research_only / diagnostic. Stage 02 added gates and evidence, but did not make outputs validated or decision-ready.
```

## Required commands

Run:

```bash
git diff --check
python -m compileall -q src tests
pytest -q tests/test_readiness_gate.py tests/test_causal_cache_audit.py tests/test_private_path_hygiene.py
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

If `python` is unavailable, use `.venv/bin/python` and document it.

If local DB is available, optionally run:

```bash
python -m src.evaluation.readiness_gate \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/readiness_gate/stage02_wp_c_readiness_gate_report.md \
  --summary-json reports/readiness_gate/stage02_wp_c_readiness_gate_report.json \
  --no-fetch
```

Do not commit DuckDB or WAL.

## Index update

If all checks pass, update `docs/indexes/WORK_PACKAGE_INDEX.md`:

```text
STAGE02-WP-A-v1 -> archived / accepted
STAGE02-WP-B-v1 -> archived / accepted
STAGE02-WP-C-v1 -> archived / accepted
STAGE02-WP-D-v1 -> archived / accepted
```

No Stage 03 package should be activated in this PR.

## Return format

```text
WP: STAGE02-WP-D-v1
status: pass / partial / fail
branch: stage02/wp-d-final-integration-acceptance
PR: ...
commands run:
- ...
merged PRs checked:
- PR #9: ...
- PR #10: ...
- PR #11: ...
final verdict: ...
readiness conclusion: ...
blocking issues:
- ...
tracked risks:
- ...
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```
