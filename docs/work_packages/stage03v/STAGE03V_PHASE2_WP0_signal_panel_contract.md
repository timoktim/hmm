# STAGE03V_PHASE2_WP0_signal_panel_contract

Stage: 03V Phase 2 / Baseline-first risk-control architecture

Work package: PHASE2-WP0

Index id: `STAGE03V-PHASE2-WP0-v1`

Suggested branch: `stage03v/phase2-wp0-signal-panel-contract`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_PHASE2_WP0_signal_panel_contract.md`

Date: 2026-06-12

## Objective

Implement the first Stage03V Phase 2 user-facing risk signal panel.

This package creates a read-only signal snapshot adapter and a Streamlit `信号面板` page under the `当前状态` navigation group. The page must organize existing validated signals into an artificial-decision support surface for human review, not a trading or execution engine.

The panel must reflect the Stage03V1 closeout conclusion:

```text
baseline-first risk-control architecture
primary baseline family: realized_volatility
model role: research_only_hazard_overlay
HMM / HSMM role: context only
prospective holdout: not consumed
no trading or decision output
```

## Required preconditions

This package may proceed only if all are true:

```text
PR91 / STAGE03V-CLOSEOUT1-v1 is merged.
reports/stage03v/stage03v1_phase1_closeout_report.json status = pass
reports/stage03v/stage03v1_phase2_handoff.json status = pass
recommended_phase2_direction = baseline_first_risk_control_architecture
stage03v1_decision_support_status = not_promoted
stage03v1_model_usage_status = research_only_overlay
stage03v1_baseline_usage_status = volatility_baseline_primary_for_risk_control_research
prospective_holdout_rows_evaluated = 0
prospective_holdout_consumption_count = 0
```

If any precondition fails, emit `blocked_closeout_not_accepted` and stop.

## Required route anchors

Read these first:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_CLOSEOUT1_artifact_freeze.md
docs/roadmap/STAGE03V_PHASE1_CLOSEOUT_AND_PHASE2_HANDOFF.md
reports/stage03v/stage03v1_phase1_closeout_report.json
reports/stage03v/stage03v1_phase2_handoff.json
reports/stage03v/stage03v1_artifact_freeze_manifest.json
reports/stage03v/stage03v1_invalidated_artifact_registry.json
reports/stage03v/stage03v1_final_gate_v2_report.json
reports/stage03v/calibration_readiness_report.json
reports/stage03v/downside_readiness_matrix.csv
reports/stage03v/downshift_experiment_report.json
src/ui/dashboard.py
src/ui/lifecycle_page.py
src/ui/navigation.py
app.py
src/features/sector_features.py
src/models/inference.py
src/models/market_hmm.py
```

## Stage boundary

Allowed:

- Add a new read-only `信号面板` UI page.
- Add a read-only signal snapshot adapter that joins or computes current display signals from existing DB tables and accepted artifacts.
- Compute display-only baseline indicators from `sector_ohlcv` / `sector_features` if the required historical OHLCV rows exist.
- Read HMM causal state outputs already available through existing inference helpers.
- Read HSMM lifecycle UI fields already available in `hsmm_lifecycle_ui_daily`.
- Read Stage03V readiness artifacts and display readiness-gated probability availability.
- Add tests for schema, readiness gating, no-trading-output vocabulary, missing-data behavior, and navigation wiring.

Forbidden:

- Do not train, refit, or tune any model.
- Do not recalibrate probabilities.
- Do not generate new Stage03V probability models.
- Do not consume, score, inspect, or evaluate prospective holdout performance.
- Do not modify target definitions, readiness thresholds, exposure rules, bucket rules, folds, or RERUN1 artifacts.
- Do not implement Stage03V2 or Stage03V3.
- Do not create buy/sell/position-sizing/portfolio-action/execution/recommendation outputs.
- Do not write persistent DuckDB tables unless explicitly limited to optional user-facing UI preferences; default implementation should be stateless/read-only.
- Do not commit full target, feature, raw-score, calibrated-score, exposure, or event matrices.

## Page location and navigation

Add a new page:

```text
label: 信号面板
group: 当前状态
advanced: false
```

Required code changes:

```text
src/ui/signal_panel_page.py
src/signals/signal_panel_snapshot.py
tests/test_signal_panel_snapshot.py
tests/test_signal_panel_ui_contract.py
```

Update:

```text
src/ui/navigation.py
app.py
```

The page should be directly visible under `当前状态`, not hidden behind advanced mode.

## Signal groups

### 1. Baseline-first volatility risk band

Primary signal group. Use realized-volatility baselines as the main risk-control reference.

Minimum display fields:

```text
signal_date
sector_id
sector_name
vol_20d
vol_60d
ewma_vol
volatility_band
volatility_percentile_cs
volatility_percentile_ts_if_available
volatility_primary_source
volatility_signal_status
```

Implementation notes:

- Existing `sector_features.vol_20d` may be used when available.
- `vol_60d` and `ewma_vol` may be computed read-only from `sector_ohlcv` if not already stored.
- The panel must label these as baseline/reference risk indicators, not trade instructions.
- HAR forecast band is a future extension. Do not force HAR into this first package unless a pre-existing validated HAR artifact already exists.

### 2. Downside volatility asymmetry

Minimum display fields:

```text
downside_vol_20d
downside_vol_60d
downside_vol_share_20d
downside_vol_share_60d
negative_return_day_share_20d
negative_return_day_share_60d
downside_asymmetry_band
```

Definition guidance:

```text
downside_vol_window = sqrt(mean(min(ret, 0)^2)) over window
total_vol_window = std(ret) over window
downside_vol_share_window = downside_vol_window / total_vol_window when total_vol_window > 0
negative_return_day_share_window = count(ret < 0) / valid_return_count
```

No lookahead. Use only returns available through the latest selected signal date.

### 3. HMM state context

Context signal group only.

Minimum display fields where available:

```text
hmm_state_label
hmm_state_source
hmm_confidence
prob_trend_up
prob_neutral
prob_risk_off
recent_state_switch_date
recent_state_switch_flag
```

Use existing causal state helpers first. Do not default to in-sample states unless the UI clearly labels them as in-sample display only and hides them from primary ranking.

### 4. HSMM lifecycle context

Context signal group only.

Minimum display fields where available:

```text
hsmm_state_phase
hsmm_state_age_days
hsmm_age_bucket
hsmm_duration_percentile
exit_tendency_1d
exit_tendency_3d
exit_tendency_5d
exit_tendency_10d
exit_tendency_20d
next_state_tendency
hsmm_probability_display_policy
```

Use `hsmm_lifecycle_ui_daily` where present. If missing, show unavailable status and do not fail the whole page.

### 5. Stage03V risk tendency and readiness-gated probability display

Display Stage03V readiness and risk tendency under strict readiness rules.

Minimum display fields:

```text
stage03v_readiness_summary
stage03v_usable_probability_slice_count
stage03v_ordinal_only_slice_count
stage03v_baseline_only_slice_count
stage03v_research_only_slice_count
stage03v_probability_display_status
stage03v_probability_source_status
stage03v_risk_ordinal
stage03v_calibrated_probability_available
stage03v_calibrated_probability_fields
```

Rules:

- Do not synthesize sector-level calibrated probabilities from aggregate reports.
- If no current per-entity calibrated score source exists, display `stage03v_probability_source_status = unavailable_current_per_entity_score_source`.
- The 5 usable slices may be shown as readiness evidence and as probability-display candidates only if an actual current per-entity calibrated-score source exists.
- `ordinal_only_candidate` rows may show only low/medium/high/extreme or equivalent ordinal tendency, not numeric probability.
- `baseline_only_candidate` rows may show only baseline-derived risk band.
- `research_only` rows may be hidden by default or shown in an advanced expander, never as decision-ready values.

### 6. Model-vs-baseline conflict indicator

Add a non-decision explanation field:

```text
model_baseline_alignment_status
```

Allowed values:

```text
baseline_high_model_high
baseline_high_model_low
baseline_low_model_high
baseline_low_model_low
baseline_available_model_unavailable
model_available_baseline_unavailable
insufficient_signal_sources
```

Interpretation must be phrased as research/reference only:

```text
baseline_high_model_high: risk evidence aligned
baseline_high_model_low: possible baseline false-alarm / overlay disagreement
baseline_low_model_high: possible residual risk / overlay disagreement
baseline_low_model_low: low-risk alignment
```

Do not convert this into buy/sell/position-size output.

## Snapshot schema

Create a canonical snapshot dataframe from `src/signals/signal_panel_snapshot.py`.

Required columns:

```text
signal_date
sector_id
sector_name
sector_type
data_freshness_status
source_scope
vol_20d
vol_60d
ewma_vol
volatility_band
volatility_percentile_cs
downside_vol_share_20d
downside_vol_share_60d
negative_return_day_share_20d
hmm_state_label
hmm_confidence
prob_trend_up
prob_neutral
prob_risk_off
hsmm_state_phase
hsmm_state_age_days
hsmm_age_bucket
hsmm_duration_percentile
exit_tendency_5d
exit_tendency_10d
exit_tendency_20d
stage03v_readiness_summary
stage03v_probability_display_status
stage03v_probability_source_status
stage03v_risk_ordinal
model_baseline_alignment_status
human_review_note
not_trading_output
```

`not_trading_output` must always be `yes`.

Forbidden column-name tokens outside explicit negative guard fields:

```text
buy
sell
position_size
position_sizing
recommendation
execution
trade_instruction
portfolio_action
```

## UI layout

The `信号面板` page must show:

1. Header warning / positioning:

```text
此页面为研究信号与人工判断参考，不构成交易、仓位、买卖或执行建议。
```

2. Top summary cards:

```text
Signal date
Data freshness
Primary baseline risk band distribution
HMM state distribution
HSMM lifecycle availability
Stage03V readiness / probability source status
```

3. Main signal table with filters:

```text
sector_type
sector_name search
volatility_band
model_baseline_alignment_status
HMM state
HSMM phase
Stage03V readiness
show only high baseline risk
show only model-baseline disagreement
```

4. Expanders:

```text
Baseline volatility details
HMM/HSMM context details
Stage03V readiness and probability display policy
Evidence and artifact provenance
```

5. Missing-data behavior:

- If no HMM causal cache is available, show HMM context unavailable but still show baseline signals if possible.
- If no HSMM lifecycle table/run is available, show HSMM context unavailable but still show baseline signals if possible.
- If Stage03V calibrated per-entity score source is absent, show readiness metadata and probability-source unavailable; do not fail the page.

## Evidence and provenance

The page must expose a small provenance block:

```text
Stage03V closeout verdict path
Stage03V final gate v2 path
Stage03V readiness matrix path
Stage03V invalidated artifact registry path
HMM state source
HSMM lifecycle source
baseline data source
```

It must explicitly warn that old pre-RERUN1 WP4-WP6 and old WP7-v1 artifacts are invalidated and must not be cited as signal-strength evidence.

## Required deliverables

Create:

```text
src/signals/signal_panel_snapshot.py
src/ui/signal_panel_page.py
tests/test_signal_panel_snapshot.py
tests/test_signal_panel_ui_contract.py
docs/runtime/STAGE03V_SIGNAL_PANEL_CONTRACT.md
reports/stage03v/phase2_signal_panel_contract.json
```

Update:

```text
src/ui/navigation.py
app.py
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

Optional if useful:

```text
src/signals/__init__.py
```

## Required CLI / test behavior

No standalone empirical CLI is required for this package unless the implementation benefits from one. Prefer pure functions and unit tests for the snapshot adapter.

Minimum commands:

```bash
python -m compileall -q src tests
pytest -q tests/test_signal_panel_snapshot.py tests/test_signal_panel_ui_contract.py
pytest -q -m "not slow"
bash scripts/check_no_private_paths.sh
git diff --check
git diff --cached --check
```

## Test requirements

Minimum synthetic coverage:

- Snapshot builder returns required schema columns.
- `not_trading_output` is always `yes`.
- Forbidden trading/action tokens do not appear as output column names, except explicit negative guard fields if any.
- Volatility bands are computed without lookahead from synthetic OHLCV rows.
- Downside volatility share handles zero-volatility and all-positive-return windows safely.
- HMM context missing does not fail baseline signal rendering.
- HSMM context missing does not fail baseline signal rendering.
- Stage03V per-entity calibrated probability is not displayed when the current calibrated-score source is missing.
- `usable_probability_candidate` can expose probability display only when a current per-entity calibrated-score source is present.
- `ordinal_only_candidate` cannot expose numeric probability fields.
- Invalidated pre-RERUN1 artifacts are not used as signal sources.
- Navigation includes `信号面板` under `当前状态` and app routes to `render_signal_panel_page`.

## Acceptance criteria

PHASE2-WP0 passes if:

- PR91 / CLOSEOUT1 is accepted and merged before execution.
- A visible `信号面板` page is added under `当前状态`.
- The signal page renders from a canonical snapshot adapter.
- Baseline volatility signals are the primary risk layer.
- Downside-volatility asymmetry is displayed when enough OHLCV history exists.
- HMM and HSMM fields are displayed as context, not decision outputs.
- Stage03V readiness and probability display obey readiness restrictions.
- Missing HMM/HSMM/Stage03V probability sources degrade gracefully.
- No new model training, recalibration, readiness reassignment, holdout consumption, Stage03V2/3 implementation, or trading/decision output occurs.
- Tests and CI pass.

## Return format

```text
index_id: STAGE03V-PHASE2-WP0-v1
branch: stage03v/phase2-wp0-signal-panel-contract
PR: ...
status: pass / partial / fail

commands run:
- ...

files changed:
- ...

CLOSEOUT1 accepted: yes/no
signal panel page added: yes/no
snapshot adapter added: yes/no
navigation route added: yes/no
required schema columns present: yes/no
baseline volatility layer available: yes/no
downside volatility asymmetry available: yes/no
HMM context available: yes/no / unavailable_graceful
HSMM context available: yes/no / unavailable_graceful
Stage03V readiness display available: yes/no
Stage03V calibrated probability source: available / unavailable_current_per_entity_score_source
Stage03V probability display gated: yes/no
invalidated artifacts excluded from signal sources: yes/no

external data fetch: no
new experiment run: no
model training: no
probability recalibration: no
readiness reassigned: no
target dataset modified: no
fixed threshold mainline modified: no
prospective holdout performance consumed: no
holdout consumed: no
HMM/HSMM training modified: no
Stage03V2 implemented: no
Stage03V3 implemented: no
trading or decision output: no

remaining risks:
- ...
```
