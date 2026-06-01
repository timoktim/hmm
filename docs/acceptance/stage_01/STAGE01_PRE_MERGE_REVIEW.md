# STAGE01_PRE_MERGE_REVIEW

Project: HMM / HSMM analyzer development
Stage: 01
Date: 2026-06-01
Status: pre-merge review

## Current PRs

| PR | branch | claimed scope | status | initial review |
|---|---|---|---|---|
| #6 | `stage01/wp-a-hmm-confidence` | STAGE01-WP-A HMM confidence diagnostics | draft/open | code/tests look scoped; report is `partial_missing_db` |
| #7 | `stage01/wp-b-hmm-label-alignment` | STAGE01-WP-B HMM label alignment | draft/open | code/tests look scoped; report is partial because DB missing |
| #5 | `stage01/wp-c-hmm-churn-dwell-ui` | STAGE01-WP-C HMM churn/dwell diagnostics and readiness downgrade | draft/open | code/tests look scoped; modifies readiness policy; report is partial because DB missing |

## Key finding

All three Stage 01 PRs are structurally useful but currently only partially validated. The committed reports were generated without the local V0 database:

```text
data/db/a_share_hmm.duckdb
```

Therefore they prove that the modules compile, unit tests pass, and missing-DB degradation works. They do not yet prove that the diagnostics work on the actual V0 local dataset.

## Required data validation before merge

Each PR must be rerun in an environment where the existing V0 local database is available at:

```text
data/db/a_share_hmm.duckdb
```

No external data fetching is allowed. If the DB is copied into the working tree, it must remain uncommitted and covered by `.gitignore`.

### PR #6 / WP-A confidence

Required command:

```bash
python -m src.evaluation.hmm_confidence \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --output reports/hmm_confidence/stage01_wp_a_confidence_report.md \
  --summary-json reports/hmm_confidence/stage01_wp_a_confidence_report.json \
  --no-fetch
```

Acceptance expectations:

- report status must not remain `partial_missing_db`;
- `local_db_used` should be true;
- `run_id` should resolve to an actual HMM run or report a precise missing-run reason;
- posterior columns should be found or report a precise schema mismatch;
- report must keep HMM posterior semantics as state confidence only.

### PR #7 / WP-B label alignment

Required command:

```bash
python -m src.evaluation.hmm_label_alignment \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --compare-mode recent-runs \
  --output reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.md \
  --summary-json reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json \
  --no-fetch
```

Acceptance expectations:

- report status must not remain `partial` solely due to DB absence;
- at least one run pair should be evaluated if historical runs exist;
- if not enough historical runs exist, report must state `insufficient_run_pairs` rather than generic DB missing;
- output should include alignment method, label preservation, ambiguity, and drift severity.

### PR #5 / WP-C churn/dwell

Required command:

```bash
python -m src.evaluation.hmm_churn_dwell \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --output reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.md \
  --summary-json reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.json \
  --no-fetch
```

Acceptance expectations:

- report status must not remain partial due to DB absence;
- state rows should be found or report a precise missing state table / run reason;
- churn/dwell rows should be generated when state rows exist;
- readiness downgrade logic must remain conservative;
- it must not depend on WP-A/WP-B being already merged unless it explicitly handles missing confidence/alignment inputs.

## Merge order

Recommended merge order after data validation:

1. PR #6: HMM confidence diagnostics.
2. PR #7: HMM label alignment.
3. PR #5: HMM churn/dwell diagnostics and UI/readiness degradation.

Reason:

- confidence is a base diagnostic;
- label alignment is another base diagnostic;
- churn/dwell can consume or degrade based on confidence/alignment availability, so it should merge last.

## Additional instructions for Codex

Each PR should update its body after data validation with:

```text
Data validation:
- local DB available: yes/no
- run_id resolved: ...
- report status: ...
- rows generated: ...
- external data fetch: no
- training algorithm modified: no
- report files updated: yes/no
```

The PRs should remain draft until this data validation is complete.

## Current gate

Current recommendation: do not merge PR #5/#6/#7 yet. Request data-backed reruns first.
