# STAGE03V Signal Panel Contract

Date: 2026-06-12

Index id: `STAGE03V-PHASE2-WP0-v1`

Status: implemented_pending_acceptance

## Purpose

`当前状态 / 信号面板` is a read-only research panel for human review. It organizes accepted Stage03V Phase 1 evidence with current baseline, HMM, and HSMM context.

## Signal Hierarchy

```text
primary_layer: realized_volatility_baseline_risk_band
context_layers: HMM state, HSMM lifecycle
stage03v_layer: readiness-gated risk tendency
model_role: research_only_hazard_overlay
decision_support_status: not_promoted
```

## Snapshot Adapter

Canonical adapter:

```text
src/signals/signal_panel_snapshot.py
```

Required snapshot columns:

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

## Probability Display Policy

Default Stage03V probability source status:

```text
unavailable_current_per_entity_score_source
```

Numeric Stage03V probabilities may be displayed only when a current per-entity calibrated score source exists. Aggregate Stage03V reports are readiness evidence only and must not be used to synthesize sector-level calibrated probabilities.

`ordinal_only_candidate` rows may show ordinal tendency only. `baseline_only_candidate` rows may show baseline-derived risk bands only. `research_only` rows must not be displayed as decision-ready values.

## Provenance

Accepted signal source paths:

```text
reports/stage03v/stage03v1_phase1_closeout_report.json
reports/stage03v/stage03v1_final_gate_v2_report.json
reports/stage03v/downside_readiness_matrix.csv
reports/stage03v/stage03v1_invalidated_artifact_registry.json
sector_ohlcv / sector_features
walk_forward_state_cache
hsmm_lifecycle_ui_daily
```

Invalidated artifacts forbidden as signal sources:

```text
reports/stage03v/purge_embargo_fold_plan.json
reports/stage03v/risk_validation_report.json
reports/stage03v/downshift_research_report.json
reports/stage03v/wp7_final_gate_input_manifest.json
old WP7-v1 final gate outputs
```

## Boundaries

```text
external_data_fetch: no
new_experiment_run: no
model_training: no
probability_recalibration: no
readiness_reassigned: no
target_dataset_modified: no
fixed_threshold_mainline_modified: no
prospective_holdout_performance_consumed: no
holdout_consumed: no
HMM_HSMM_training_modified: no
Stage03V2_implemented: no
Stage03V3_implemented: no
trading_or_decision_output: no
```
