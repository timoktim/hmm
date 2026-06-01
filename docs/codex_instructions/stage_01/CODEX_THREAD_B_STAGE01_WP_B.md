# CODEX_THREAD_B_STAGE01_WP_B

Repository: timoktim/hmm
Index id: STAGE01-WP-B-v1
Work package: docs/work_packages/stage_01/STAGE01_WP_B_hmm_label_alignment_stability.md
Suggested branch: stage01/wp-b-hmm-label-alignment

## Instruction

Start from updated `main`. Open `docs/indexes/WORK_PACKAGE_INDEX.md`, confirm `STAGE01-WP-B-v1` is active, then execute only the WP-B work package.

Your task is to build HMM label-alignment and state-identity stability diagnostics. Do not implement WP-A confidence metrics except consuming them if present. Do not implement WP-C churn/dwell/UI degradation. Do not change HMM/HSMM training algorithms. Do not fetch external data.

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_hmm_label_alignment.py
pytest -q -m "not slow"
python -m src.evaluation.hmm_label_alignment --db data/db/a_share_hmm.duckdb --run-id latest --compare-mode recent-runs --output reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.md --summary-json reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json --no-fetch
```

If comparable runs are unavailable, produce a partial report instead of crashing.

## Return format

Use the return contract in the work package.
