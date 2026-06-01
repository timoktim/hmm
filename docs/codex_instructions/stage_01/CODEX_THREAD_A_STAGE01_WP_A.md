# CODEX_THREAD_A_STAGE01_WP_A

Repository: timoktim/hmm
Index id: STAGE01-WP-A-v1
Work package: docs/work_packages/stage_01/STAGE01_WP_A_hmm_confidence_metrics.md
Suggested branch: stage01/wp-a-hmm-confidence

## Instruction

Start from updated `main`. Open `docs/indexes/WORK_PACKAGE_INDEX.md`, confirm `STAGE01-WP-A-v1` is active, then execute only the WP-A work package.

Your task is to build HMM confidence metrics and reports. Do not implement WP-B label alignment or WP-C churn/dwell/UI degradation. Do not change HMM/HSMM training algorithms. Do not fetch external data.

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_hmm_confidence.py
pytest -q -m "not slow"
python -m src.evaluation.hmm_confidence --db data/db/a_share_hmm.duckdb --run-id latest --output reports/hmm_confidence/stage01_wp_a_confidence_report.md --summary-json reports/hmm_confidence/stage01_wp_a_confidence_report.json --no-fetch
```

If the DB or posterior columns are unavailable, produce a partial report instead of crashing.

## Return format

Use the return contract in the work package.
