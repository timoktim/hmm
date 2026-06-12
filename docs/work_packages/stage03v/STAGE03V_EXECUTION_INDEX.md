# STAGE03V_EXECUTION_INDEX

Status: active
Stage: 03V / Volatility and downside-risk hazard
Active package: STAGE03V-WP7-v2

## Audit Notice and RERUN1 Supersession

The Stage03V1 post-completion audit found that the original WP2 fold plan used by WP4-WP6 covered only a 2014 micro-window from the WP2 audit sample. The old WP4-WP6 empirical outputs were therefore invalidated as evidence of signal strength or weakness, although their engineering and boundary discipline remained useful.

FIX1 archived the contract repairs. RERUN1 archived the full-scale revalidation: fold plan v2 magnitude gate, WP4 logistic rerun, WP5 calibration/readiness rerun, and B2 three-arm downshift experiment. PR89 merged RERUN1 and WP7-v2 is now active.

WP7-v1 is superseded/closed. WP7-v2 must use RERUN1 artifacts and must not use the old WP6 tier aggregation outputs as final evidence.

## Purpose

Stage03V defines a volatility and downside-risk hazard route after Stage03R and Stage04 validation discipline. Stage03V1 built and audited downside-risk event targets, causal baselines, logistic hazard, calibration/readiness, and historical-development risk-validation evidence. RERUN1 replaced invalidated microfold evidence with full-scale validation. WP7-v2 now produces the Stage03V1 final gate verdict after RERUN1.

WP7-v2 must express the actual RERUN1 result: model discrimination is valid, but the volatility baseline is superior on pre-registered primary risk downshift metrics. These facts must be reported separately.

## Route Anchors

- `docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md`
- `docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md`
- `docs/work_packages/stage03v/STAGE03V_WP0_scope_freeze_contracts_ledger.md`
- `docs/work_packages/stage03v/STAGE03V_WP0.5_sample_feasibility_preflight.md`
- `docs/work_packages/stage03v/STAGE03V_WP1_risk_event_target_dataset_v1.md`
- `docs/work_packages/stage03v/STAGE03V_WP2_target_leakage_purge_embargo_ci_gate.md`
- `docs/work_packages/stage03v/STAGE03V_WP2.1_full_target_streaming_audit.md`
- `docs/work_packages/stage03v/STAGE03V_WP3_volatility_range_empirical_baselines.md`
- `docs/work_packages/stage03v/STAGE03V_WP3.5_volatility_scaled_threshold_sanity_gate.md`
- `docs/work_packages/stage03v/STAGE03V_WP4_logistic_downside_risk_hazard_v1.md`
- `docs/work_packages/stage03v/STAGE03V_WP5_calibration_clustered_inference_readiness.md`
- `docs/work_packages/stage03v/STAGE03V_WP6_risk_validation_protocol_downshift_report.md`
- `docs/work_packages/stage03v/STAGE03V_FIX1_contract_repairs.md`
- `docs/work_packages/stage03v/STAGE03V_RERUN1_full_scale_revalidation.md`
- `docs/work_packages/stage03v/STAGE03V_WP7_stage03v1_final_gate.md`
- `docs/work_packages/stage03v/STAGE03V_WP7_v2_stage03v1_final_gate_rerun1.md`
- `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP7_v2_stage03v1_final_gate_rerun1.md`
- `reports/stage03v/purge_embargo_fold_plan_v2.json`
- `reports/stage03v/fold_plan_magnitude_overview.md`
- `reports/stage03v/fold_plan_magnitude_overview.csv`
- `reports/stage03v/validation_trial_accounting.json`
- `reports/stage03v/logistic_hazard_report.json`
- `reports/stage03v/calibration_readiness_report.json`
- `reports/stage03v/downshift_experiment_report.json`
- `reports/stage03v/downshift_experiment_arm_metrics.csv`

## Package Sequence

| index_id | package | status | branch | purpose |
|---|---|---|---|---|
| STAGE03V-WP0-v1 | Scope Freeze, Contracts, Ledger | archived | stage03v/wp0-scope-freeze-contracts-ledger | freeze Stage03V scope, signal contract, readiness policy, SW2021 L2 universe, and Stage03V holdout registration |
| STAGE03V-WP0.5-v1 | Sample Feasibility Preflight | archived | stage03v/wp0.5-sample-feasibility-preflight | count downside-risk event feasibility evidence before target dataset construction |
| STAGE03V-WP1-v1 | Risk Event Target Dataset v1 | archived | stage03v/wp1-risk-event-target-dataset-v1 | build formal downside-risk target dataset builder and synthetic path-target tests |
| STAGE03V-WP2-v1 | Target Leakage, Purge, Embargo, and CI Gate | archived | stage03v/wp2-target-leakage-purge-embargo-ci-gate | enforce target controls before baseline or model packages open |
| STAGE03V-WP2.1-v1 | Full Target Streaming Audit | archived | stage03v/wp2.1-full-target-streaming-audit | run full-target streaming / blockwise audit before baseline packages open |
| STAGE03V-WP3-v1 | Volatility, Range-Based, Empirical, and Continuous Diagnostic Baselines | archived | stage03v/wp3-volatility-range-empirical-baselines | add causal baseline diagnostics after target controls and full-target audit pass |
| STAGE03V-WP3.5-v1 | Volatility-Scaled Threshold Supplement and Baseline Metric Sanity Gate | archived | stage03v/wp3.5-volatility-scaled-threshold-sanity | evaluate volatility-scaled threshold supplement and audit WP3 metric artifacts before WP4 opens |
| STAGE03V-WP4-v1 | Logistic Downside Risk Hazard v1 | archived_invalidated_by_microfold_audit | stage03v/wp4-logistic-downside-risk-hazard-v1 | original logistic rerun evidence invalidated by microfold coverage |
| STAGE03V-WP5-v1 | Calibration, Clustered Inference, and Downside Risk Readiness Matrix | archived_invalidated_by_microfold_audit | stage03v/wp5-calibration-clustered-readiness | original calibration evidence invalidated by microfold coverage |
| STAGE03V-WP6-v1 | Risk Validation Protocol and Downshift Research Report | archived_invalidated_by_microfold_audit | stage03v/wp6-risk-validation-downshift-report | original downshift tier aggregation invalidated and replaced by RERUN1 B2 |
| STAGE03V-FIX1-v1 | Contract Repairs | archived | stage03v/fix1-contract-repairs | close audit findings F1-F6 in evaluation code before full-scale rerun |
| STAGE03V-RERUN1-v1 | Full-Scale Revalidation | archived | stage03v/rerun1-full-scale-revalidation | accepted full-scale fold plan v2, WP4/WP5 rerun, and B2 three-arm downshift experiment |
| STAGE03V-WP7-v1 | Stage03V1 Final Gate | superseded_closed | stage03v/wp7-stage03v1-final-gate | old final gate superseded by RERUN1 and WP7-v2 delta requirements |
| STAGE03V-WP7-v2 | Stage03V1 Final Gate after RERUN1 | active | stage03v/wp7-v2-stage03v1-final-gate-rerun1 | produce final gate verdict using RERUN1 artifacts, expanded B2 verdict states, and registered holdout thresholds |

## Execution Rules

1. Only STAGE03V-WP7-v2 is executable in the current Stage03V branch sequence.
2. WP7-v2 must use RERUN1 artifacts: `purge_embargo_fold_plan_v2.json`, regenerated WP4/WP5 reports, and `downshift_experiment_report.json` / arm metrics.
3. WP7-v2 must not use old WP6 `risk_validation_report.json`, `downshift_research_report.json`, or `wp7_final_gate_input_manifest.json` as final evidence.
4. WP7-v2 must separate model discrimination from primary-risk downshift comparison.
5. WP7-v2 must be able to emit `baseline_superior_on_primary_risk_metrics`.
6. WP7-v2 must enforce registered holdout thresholds: 120 complete 20d-label trade dates and at least 2 market event blocks.
7. WP7-v2 must reject the old accidental 60-day / 1-block holdout minimum.
8. WP7-v2 must not train models, recalibrate probabilities, reassign readiness, or consume prospective holdout unless explicitly authorized.
9. WP7-v2 must not produce trading, buy/sell, sizing, recommendation, execution, portfolio-action, or UI decision outputs.
10. Stage03V2 and Stage03V3 remain placeholders.

## WP7-v2 Expected Deliverables

- `src/evaluation/stage03v_final_gate_v2.py`
- `scripts/stage03v_final_gate_v2.sh`
- `tests/test_stage03v_final_gate_v2.py`
- `tests/test_stage03v_final_gate_v2_boundaries.py`
- `configs/stage03v_final_gate_policy_v2.yaml`
- `reports/stage03v/stage03v1_final_gate_v2_report.md`
- `reports/stage03v/stage03v1_final_gate_v2_report.json`
- `reports/stage03v/stage03v1_final_gate_v2_verdict.json`
- `reports/stage03v/stage03v1_final_gate_v2_evidence_matrix.csv`
- `reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json`
- `reports/stage03v/stage03v1_final_gate_v2_rerun1_input_manifest.json`
- `reports/stage03v/stage03v1_prospective_holdout_status_v2.json`
- `reports/stage03v/stage03v1_post_gate_action_plan_v2.md`
- `reports/stage03v/stage03v1_final_gate_v2_audit_sample.csv`

## Locked Dates and Holdout Requirement

```text
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
prospective_holdout_min_complete_20d_label_trade_dates: 120
prospective_holdout_min_market_event_blocks: 2
```

The 120 / 2 holdout minimum is registered and must not be silently relaxed.

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-10 | Activated STAGE03V-WP0-v1 and blocked WP0.5 plus later packages until WP0 acceptance. | Codex |
| 2026-06-10 | Accepted STAGE03V-WP0.5-v1 sample feasibility preflight. | Codex |
| 2026-06-10 | Implemented WP1-WP3 baseline/target/control packages. | Codex |
| 2026-06-11 | Implemented WP3.5-WP6 original packages; later empirical evidence invalidated by microfold audit. | Codex |
| 2026-06-12 | Implemented FIX1 and accepted RERUN1 full-scale revalidation in PR89. | Codex |
| 2026-06-12 | Activated STAGE03V-WP7-v2 after RERUN1 with RERUN1 inputs, expanded B2 verdict states, and corrected holdout thresholds. | ChatGPT |
