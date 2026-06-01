# CODEX_THREAD_C_STAGE01_WP_C

Repository: timoktim/hmm
Index id: STAGE01-WP-C-v1
Work package: docs/work_packages/stage_01/STAGE01_WP_C_hmm_churn_dwell_ui_readiness.md
Suggested branch: stage01/wp-c-hmm-churn-dwell-ui

## Instruction

Start from updated `main`. Open `docs/indexes/WORK_PACKAGE_INDEX.md`, confirm `STAGE01-WP-C-v1` is active, then execute only the referenced work package.

Your task is to build HMM churn and dwell monitoring plus conservative readiness downgrades. You may consume WP-A or WP-B outputs if present, but the package must still work without them.

Do not implement WP-A confidence metrics. Do not implement WP-B label alignment. Do not change HMM or HSMM training algorithms. Do not fetch external data.

## Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_hmm_churn_dwell.py
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
pytest -q -m "not slow"
python -m src.evaluation.hmm_churn_dwell --db data/db/a_share_hmm.duckdb --run-id latest --output reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.md --summary-json reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.json --no-fetch
```

If local DB content is insufficient, produce a partial report instead of crashing.

## Return format

Use the return contract in the work package.
