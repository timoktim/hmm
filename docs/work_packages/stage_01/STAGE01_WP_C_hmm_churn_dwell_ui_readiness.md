# STAGE01_WP_C_hmm_churn_dwell_ui_readiness

Stage: 01 / HMM baseline strengthening  
Work package: WP-C  
Index id: STAGE01-WP-C-v1  
Suggested branch: `stage01/wp-c-hmm-churn-dwell-ui`  
Codex thread: C  
Date: 2026-06-01

## Objective

Build HMM churn/dwell monitoring and connect low-confidence or unstable HMM states to UI/readiness degradation. This package focuses on whether the HMM state sequence is too noisy, too fragmented, or insufficiently stable to support normal display. It should consume Stage 00 readiness conventions and, if available, Stage 01 WP-A confidence outputs and WP-B label-alignment outputs.

The output is not a trading signal. It is a model reliability and UI downgrade layer.

## Stage boundary

This work package belongs to Stage 01 only. It may add churn/dwell tables, reports, and UI metadata/warnings. It must not change HMM/HSMM training algorithms. It must not implement Robust HMM, Sticky HMM, HSMM repair, duration hazard, BOCPD, or decision engine.

## Inputs

Default DB path:

```text
data/db/a_share_hmm.duckdb
```

Potential source tables:

```text
sector_state_daily
walk_forward_state_cache
model_runs
hmm_confidence_daily
hmm_confidence_run_summary
hmm_label_alignment_audit
model_evidence_registry
ui_readiness_policy
```

The implementation must work even if WP-A/WP-B outputs are not yet present. In that case, generate churn/dwell diagnostics from existing HMM state rows and mark confidence/alignment integration as unavailable.

## Required metrics

For each run and, where possible, each sector/state sequence:

- `transition_count`
- `transition_rate_1d`
- `mean_dwell_days`
- `median_dwell_days`
- `p10_dwell_days`
- `p90_dwell_days`
- `single_day_episode_share`
- `episode_count`
- `fragmentation_score`
- `churn_bucket`: `low`, `medium`, `high`, `excessive`, `unknown`
- `dwell_readiness_status`: Stage 00 canonical readiness status
- `display_action`: `normal`, `warn`, `research_only`, `hide_strategy`, `blocked`

Suggested default logic:

```text
low churn: transition_rate_1d <= 0.10 and single_day_episode_share <= 0.15
medium churn: transition_rate_1d <= 0.20 and single_day_episode_share <= 0.30
high churn: transition_rate_1d <= 0.35 or single_day_episode_share <= 0.50
excessive churn: above high thresholds
unknown: insufficient sequence length or missing state sequence
```

The exact thresholds may be configurable, but defaults must be documented.

## UI/readiness behavior

Update UI surfaces conservatively and minimally.

Required behavior:

- If HMM confidence is low or unavailable, UI must show a warning or downgrade display to research-only.
- If churn is excessive, strategy/backtest outputs must not be promoted as validated.
- If causal walk-forward cache is missing, keep Stage 00 behavior: strategy evaluation remains research-only/blocked.
- HMM posterior must remain labeled as state confidence only.
- Do not show HMM probabilities as rising/falling/profit probabilities.

Potential UI files to touch, if needed:

```text
src/ui/dashboard.py
src/ui/state_screener_page.py
src/ui/model_evaluation_page.py
src/ui/backtest_page.py
src/ui/help_texts.py
```

Avoid large UI rewrites. Prefer small badges, warnings, and metadata columns.

## Schema requirements

Create idempotent tables or produce report-only output if schema integration is risky.

### `hmm_churn_dwell_daily` or `hmm_churn_dwell_sequence`

Minimum fields:

```text
run_id
sector_id or sector_code
state_key
state_label
episode_start_date
episode_end_date
dwell_days
is_single_day_episode
feature_scope_id
universe_id
created_at
```

### `hmm_churn_dwell_run_summary`

Minimum fields:

```text
run_id
row_count
sector_count
min_trade_date
max_trade_date
transition_count
transition_rate_1d
mean_dwell_days
median_dwell_days
single_day_episode_share
episode_count
fragmentation_score
churn_bucket
dwell_readiness_status
display_action
confidence_integration_status
alignment_integration_status
report_path
created_at
```

## CLI requirements

Recommended module:

```text
src/evaluation/hmm_churn_dwell.py
```

Required CLI:

```bash
python -m src.evaluation.hmm_churn_dwell \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --output reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.md \
  --summary-json reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.json \
  --no-fetch
```

Required behavior:

- `--no-fetch` is default.
- `--run-id latest` resolves latest HMM run.
- Missing DB or missing state rows produces a partial report.
- If WP-A/WP-B tables are unavailable, mark integration unavailable but continue.
- If UI changes are made, include a text audit or specific tests proving probability language stayed constrained.

## Tests

Add tests:

```text
tests/test_hmm_churn_dwell.py
```

If UI files are touched, add or update focused UI text/readiness tests.

Minimum coverage:

- Episode/dwell computation from synthetic state sequence.
- Transition rate and single-day episode share.
- Churn bucket logic.
- Missing state rows produce partial report, not crash.
- CLI works on minimal temporary DuckDB.
- UI probability text does not reintroduce misleading terms.
- No external updater is called.

Suggested commands:

```bash
python -m compileall -q src tests
pytest -q tests/test_hmm_churn_dwell.py
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
pytest -q -m "not slow"
python -m src.evaluation.hmm_churn_dwell --db data/db/a_share_hmm.duckdb --run-id latest --output reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.md --summary-json reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.json --no-fetch
```

## Reports

Generate:

```text
reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.md
reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.json
```

Report must include:

- run_id
- row/sector/date coverage
- transition rate
- dwell distribution
- churn bucket distribution
- single-day episode share
- confidence integration status
- alignment integration status
- recommended UI display action
- external_data_fetch: no
- training_algorithm_modified: no

## Acceptance criteria

WP-C passes if:

- It computes churn/dwell metrics from valid state sequences or generates clear partial reports.
- It preserves Stage 00 readiness semantics and probability-language constraints.
- It downgrades or warns on excessive churn/low confidence rather than promoting outputs.
- New tests pass.
- No external data is fetched.
- No HMM/HSMM training algorithm is modified.

## Return format

```text
Thread: C
index_id: STAGE01-WP-C-v1
branch: stage01/wp-c-hmm-churn-dwell-ui
PR: ...
status: pass / partial / fail
commands run:
- ...
results:
- ...
state rows found: yes/no
churn/dwell rows generated: ...
UI files changed:
- ...
report paths:
- ...
DB used: yes/no
external data fetch: no
training algorithm modified: no
implemented WP-A confidence: no
implemented WP-B label alignment: no
remaining risks:
- ...
```
