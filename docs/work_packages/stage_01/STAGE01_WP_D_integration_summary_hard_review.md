# STAGE01_WP_D_integration_summary_hard_review

Stage: 01 / HMM baseline strengthening
Work package: WP-D
Index ID: STAGE01-WP-D-v1
Executor: Codex integration reviewer
Branch: `stage01/wp-d-integration-summary`

## Purpose

Stage 01 has merged three HMM baseline diagnostics:

- PR #6 / WP-A: HMM confidence metrics.
- PR #7 / WP-B: HMM label alignment and state identity audit.
- PR #5 / WP-C: HMM churn/dwell diagnostics and readiness downgrade.

This work package closes Stage 01. It must produce a final integration summary, verify that the merged diagnostics work together from updated `main`, and scan for hard issues before Stage 02 starts.

This is not a model-development package. Do not add new models, change HMM/HSMM training, fetch data, or expand signal semantics.

## Required starting point

Start from updated `main` after PR #5, PR #6, and PR #7 have all been merged.

```bash
git fetch origin
git checkout main
git pull --ff-only
```

Create a dedicated branch:

```bash
git checkout -b stage01/wp-d-integration-summary
```

## Required local DB protocol

Read first:

```text
docs/runtime/LOCAL_DB_HANDOFF.md
```

Use the existing local V0 database only. Do not fetch new data and do not create an empty replacement DB.

Preferred DB resolution:

```bash
export ASHARE_HMM_DB_PATH=/absolute/path/to/a_share_hmm.duckdb
```

Fallback:

```text
data/db/a_share_hmm.duckdb
```

DuckDB and WAL files must not be committed.

## Scope

Allowed changes:

```text
docs/acceptance/stage_01/STAGE01_FINAL_INTEGRATION_SUMMARY.md
docs/acceptance/stage_01/STAGE01_HARD_ISSUE_REVIEW.md
docs/indexes/WORK_PACKAGE_INDEX.md
reports/stage01_integration/stage01_integration_summary.md
reports/stage01_integration/stage01_integration_summary.json
```

Optional tiny script/helper is allowed only if needed for reproducible summary generation:

```text
src/evaluation/stage01_integration_summary.py
tests/test_stage01_integration_summary.py
```

Do not modify:

```text
src/models/
src/features/
src/evaluation/hmm_confidence.py
src/evaluation/hmm_label_alignment.py
src/evaluation/hmm_churn_dwell.py
src/ui/readiness_policy.py
```

Exception: if a hard issue is found that blocks Stage 01 acceptance, do not fix it inside this work package. Record it and return `partial` or `fail`.

## Required verification commands

Run from updated `main` or the WP-D branch after it is created.

Use `python` if available; otherwise `.venv/bin/python` and `.venv/bin/pytest` are acceptable, but record that choice.

```bash
python -m compileall -q src tests
pytest -q tests/test_hmm_confidence.py tests/test_hmm_label_alignment.py tests/test_hmm_churn_dwell.py
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
pytest -q -m "not slow"
```

Then run the three diagnostics in this order on the same local DB:

```bash
python -m src.evaluation.hmm_confidence \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/hmm_confidence/stage01_wp_a_confidence_report.md \
  --summary-json reports/hmm_confidence/stage01_wp_a_confidence_report.json \
  --no-fetch
```

```bash
python -m src.evaluation.hmm_label_alignment \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --compare-mode recent-runs \
  --output reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.md \
  --summary-json reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json \
  --no-fetch
```

```bash
python -m src.evaluation.hmm_churn_dwell \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.md \
  --summary-json reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.json \
  --no-fetch
```

## Required hard-issue checks

Check and document all of the following.

### Repository and package boundary

- Stage 01 does not modify HMM/HSMM training algorithms.
- Stage 01 does not add Robust HMM, Sticky HMM, Student-t emissions, BOCPD, duration hazard, or decision engine.
- Stage 01 does not fetch external market/constituent data.
- DuckDB/WAL files are not committed.
- Reports are committed only under allowed report directories.

### Data-backed diagnostics

Confirm from reports and/or DB output:

- WP-A confidence report status is `pass`.
- WP-A uses posterior columns as state confidence only.
- WP-B label alignment report status is `pass`.
- WP-B reports label preservation, ambiguity, drift, and state identity readiness.
- WP-C churn/dwell report status is `pass`.
- WP-C reports confidence integration as available.
- WP-C reports alignment integration as available.
- WP-C reports causal cache status explicitly.

### Interpretation and readiness

Document the practical implications:

- HMM confidence is internal diagnostic / state confidence, not return probability.
- Label alignment has high ambiguity (`ambiguous_match_share` may remain high); this should keep state identity readiness conservative.
- Churn/dwell metrics can be displayed as research/internal diagnostic.
- If causal cache is still missing, display/action must remain `research_only`.
- Stage 01 does not yet make the model decision-ready.

### Integration hard issues

Classify hard issues into:

```text
blocking
non_blocking_but_must_track
informational
```

A blocking issue means Stage 01 cannot be accepted. Examples:

- any diagnostic cannot run on the local V0 DB;
- external data fetch occurred;
- training algorithm was modified;
- DuckDB file was committed;
- confidence/alignment/churn reports contradict each other in run_id or row coverage;
- readiness incorrectly becomes `validated` or `decision_ready` without causal cache.

Non-blocking but must track examples:

- no GitHub Actions CI;
- causal cache metadata is unavailable;
- label alignment ambiguity remains high;
- reports rely on local DB execution logs rather than CI artifacts.

## Required final acceptance document

Create:

```text
docs/acceptance/stage_01/STAGE01_FINAL_INTEGRATION_SUMMARY.md
```

It must include:

- merged PR list and commit refs;
- commands run and results;
- local DB path used and preflight result;
- core metrics from WP-A/WP-B/WP-C;
- final verdict: `Stage01Pass`, `Stage01PassWithTrackedRisks`, or `Stage01Fail`;
- explicit statement that Stage 01 remains diagnostic/research-only unless causal cache/readiness gates later validate stronger use;
- next recommended stage.

## Required hard issue document

Create:

```text
docs/acceptance/stage_01/STAGE01_HARD_ISSUE_REVIEW.md
```

It must include:

- checklist result for each hard-issue check above;
- blocking issues: list or `none`;
- tracked risks: list;
- recommendations for Stage 02.

## Required index update

Update:

```text
docs/indexes/WORK_PACKAGE_INDEX.md
```

Set Stage 01 WP-A/WP-B/WP-C to archived/accepted if the integration review passes.

Set this WP-D to active while the PR is open. If the PR is accepted, the reviewer will later archive it.

Do not touch Stage 00 rows.

## Expected final verdict guidance

Likely expected verdict if all checks match current reports:

```text
Stage01PassWithTrackedRisks
```

Expected tracked risks:

```text
- No GitHub Actions CI.
- Causal cache unavailable, so readiness remains research_only.
- Label alignment ambiguity is high, so state identity must remain conservative.
- Diagnostics were validated against local V0 DB, not a CI-managed artifact.
```

## Return format

Return exactly this structure in the PR body and final Codex response:

```text
WP: STAGE01-WP-D-v1
status: pass / partial / fail
branch: stage01/wp-d-integration-summary
PR: ...
commands run:
- ...
local DB:
- path used: ...
- preflight: pass/fail
- opened read-only where applicable: yes/no
stage01 merged PRs checked:
- PR #6: ...
- PR #7: ...
- PR #5: ...
core metrics:
- confidence rows: ...
- confidence readiness: ...
- label alignment run pairs: ...
- ambiguous_match_share: ...
- churn/dwell rows: ...
- churn_bucket: ...
- causal_cache_available: ...
final verdict: ...
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
