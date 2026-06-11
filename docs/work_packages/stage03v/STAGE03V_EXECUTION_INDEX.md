# STAGE03V_EXECUTION_INDEX

Status: active
Stage: 03V / Volatility and downside-risk hazard
Active package: STAGE03V-WP5-v1

## Purpose

Stage03V defines a volatility and downside-risk hazard route after the Stage03R hazard-first lifecycle work and Stage04 prospective validation discipline. WP0 froze the scope, contracts, taxonomy, readiness policy, and prospective holdout registration before any target building, model training, probability calibration, or empirical holdout consumption.

WP0.5 completed sample-feasibility preflight on the V7 verified SW2021 L2 universe. WP1 completed the first formal Stage03V1 downside-risk target dataset builder and synthetic path-target tests. WP2 created the target-control gate for target leakage, permanent cross-cutoff censoring, purge/embargo, and feature/target namespace leakage policy. WP2.1 completed a full-target streaming / blockwise audit. WP3 completed causal baseline diagnostics. WP3.5 completed volatility-scaled threshold supplement and baseline metric sanity checks. WP4 completed logistic downside-risk hazard v1. WP5 is now active and implements calibration diagnostics, clustered inference, and development-only downside-risk readiness.

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
- `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP5_calibration_clustered_inference_readiness.md`
- `reports/stage03v/sample_feasibility_report.json`
- `reports/stage03v/risk_event_target_support.json`
- `reports/stage03v/target_controls_report.json`
- `reports/stage03v/full_target_streaming_audit_report.json`
- `reports/stage03v/baseline_diagnostics_report.json`
- `reports/stage03v/vol_scaled_threshold_sanity_report.json`
- `reports/stage03v/logistic_hazard_report.json`

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
| STAGE03V-WP4-v1 | Logistic Downside Risk Hazard v1 | archived | stage03v/wp4-logistic-downside-risk-hazard-v1 | train deterministic logistic downside-risk hazard on fixed-threshold Stage03V1 targets |
| STAGE03V-WP5-v1 | Calibration, Clustered Inference, and Downside Risk Readiness Matrix | active | stage03v/wp5-calibration-clustered-readiness | calibrate logistic hazard outputs and assign development-only readiness after WP4 acceptance |
| STAGE03V-WP6 | Risk Validation Protocol and Downshift Research Report | blocked_until_wp5_accepted | pending | validate research-only/downshift evidence after readiness matrix |
| STAGE03V-WP7 | Stage03V1 Final Gate | blocked | pending | produce final Stage03V1 gate after all prior packages are accepted |

## Execution Rules

1. Only STAGE03V-WP5-v1 is executable in the current Stage03V branch sequence.
2. STAGE03V-WP6 and later packages are blocked until WP5 is accepted.
3. WP5 must use the V7 DB path and accepted WP1 / WP2 / WP2.1 / WP3 / WP3.5 / WP4 artifacts as hard inputs.
4. WP5 may fit calibration candidates and assign development-only readiness categories.
5. WP5 must not consume or inspect prospective final holdout performance.
6. WP5 must not modify WP1 target rows, labels, support reports, or target universe manifests.
7. WP5 must not replace the fixed-threshold Stage03V1 target mainline with volatility-scaled labels.
8. WP5 must not train new non-logistic model families.
9. WP5 must not fetch external data.
10. WP5 must not commit full target, feature, raw score, or calibrated score matrices.
11. WP5 must not write persistent DB tables by default.
12. WP5 must not modify HMM or HSMM training algorithms.
13. WP5 must not create UI, trading, buy/sell, recommendation, sizing, or decision outputs.
14. Stage03V2 and Stage03V3 remain placeholders only unless a later reviewed package explicitly activates them.

## WP0 Accepted Deliverables

- `configs/risk_event_signal_contract_v1.yaml`
- `configs/readiness_policy_risk_event_v1.yaml`
- `configs/stage03v_sw_l2_universe_manifest_v1.yaml`
- `reports/stage04/prospective_validation_ledger.stage03v.template.jsonl`
- `reports/stage03v/stage03v_wp0_scope_freeze_report.md`
- `reports/stage03v/stage03v_wp0_scope_freeze_report.json`
- `tests/test_stage03v_contracts.py`

## WP0.5 Accepted Deliverables

- `src/evaluation/stage03v_sample_feasibility.py`
- `scripts/stage03v_sample_feasibility_gate.sh`
- `tests/test_stage03v_sample_feasibility.py`
- `reports/stage03v/sample_feasibility_report.md`
- `reports/stage03v/sample_feasibility_report.json`

## WP1 Accepted Deliverables

- `src/evaluation/stage03v_risk_target_dataset.py`
- `scripts/stage03v_risk_target_gate.sh`
- `tests/test_stage03v_risk_target_dataset.py`
- `tests/test_stage03v_path_targets.py`
- `reports/stage03v/risk_event_target_support.md`
- `reports/stage03v/risk_event_target_support.json`
- `reports/stage03v/risk_event_target_dataset_sample.csv`
- `configs/stage03v_sw_l2_target_universe_v1.yaml`

## WP2 Accepted Deliverables

- `src/evaluation/stage03v_target_controls.py`
- `scripts/stage03v_target_controls_gate.sh`
- `tests/test_stage03v_target_controls.py`
- `tests/test_stage03v_purge_embargo.py`
- `configs/stage03v_purge_embargo_policy_v1.yaml`
- `reports/stage03v/target_controls_report.md`
- `reports/stage03v/target_controls_report.json`
- `reports/stage03v/purge_embargo_fold_plan.json`
- `reports/stage03v/target_controls_audit_sample.csv`

## WP2.1 Accepted Deliverables

- `src/evaluation/stage03v_full_target_audit.py`
- `scripts/stage03v_full_target_audit_gate.sh`
- `tests/test_stage03v_full_target_audit.py`
- `reports/stage03v/full_target_streaming_audit_report.md`
- `reports/stage03v/full_target_streaming_audit_report.json`
- `reports/stage03v/full_target_streaming_audit_chunk_summary.csv`
- `reports/stage03v/full_target_streaming_audit_error_sample.csv`

## WP3 Accepted Deliverables

- `src/evaluation/stage03v_baseline_diagnostics.py`
- `scripts/stage03v_baseline_diagnostics_gate.sh`
- `tests/test_stage03v_baseline_diagnostics.py`
- `tests/test_stage03v_baseline_causality.py`
- `configs/stage03v_baseline_diagnostics_policy_v1.yaml`
- `reports/stage03v/baseline_diagnostics_report.md`
- `reports/stage03v/baseline_diagnostics_report.json`
- `reports/stage03v/baseline_diagnostics_fold_metrics.csv`
- `reports/stage03v/baseline_diagnostics_slice_metrics.csv`
- `reports/stage03v/baseline_diagnostics_audit_sample.csv`

## WP3.5 Accepted Deliverables

- `src/evaluation/stage03v_vol_scaled_threshold_sanity.py`
- `scripts/stage03v_vol_scaled_threshold_sanity_gate.sh`
- `tests/test_stage03v_vol_scaled_threshold_sanity.py`
- `tests/test_stage03v_baseline_metric_sanity.py`
- `configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml`
- `reports/stage03v/vol_scaled_threshold_sanity_report.md`
- `reports/stage03v/vol_scaled_threshold_sanity_report.json`
- `reports/stage03v/vol_scaled_threshold_slice_summary.csv`
- `reports/stage03v/baseline_metric_sanity_audit.csv`
- `reports/stage03v/asof_shift_metric_sanity.csv`

## WP4 Accepted Deliverables

- `src/evaluation/stage03v_logistic_hazard.py`
- `scripts/stage03v_logistic_hazard_gate.sh`
- `tests/test_stage03v_logistic_hazard.py`
- `tests/test_stage03v_logistic_hazard_causality.py`
- `configs/stage03v_logistic_hazard_policy_v1.yaml`
- `reports/stage03v/logistic_hazard_report.md`
- `reports/stage03v/logistic_hazard_report.json`
- `reports/stage03v/logistic_hazard_fold_metrics.csv`
- `reports/stage03v/logistic_hazard_slice_metrics.csv`
- `reports/stage03v/logistic_hazard_coefficients.csv`
- `reports/stage03v/logistic_hazard_model_manifest.json`
- `reports/stage03v/logistic_hazard_feature_audit.csv`
- `reports/stage03v/logistic_hazard_audit_sample.csv`

## WP5 Expected Deliverables

- `src/evaluation/stage03v_calibration_readiness.py`
- `scripts/stage03v_calibration_readiness_gate.sh`
- `tests/test_stage03v_calibration_readiness.py`
- `tests/test_stage03v_calibration_causality.py`
- `configs/stage03v_calibration_readiness_policy_v1.yaml`
- `reports/stage03v/calibration_readiness_report.md`
- `reports/stage03v/calibration_readiness_report.json`
- `reports/stage03v/calibration_fold_metrics.csv`
- `reports/stage03v/calibration_slice_metrics.csv`
- `reports/stage03v/calibration_curve_bins.csv`
- `reports/stage03v/clustered_inference_summary.csv`
- `reports/stage03v/downside_readiness_matrix.csv`
- `reports/stage03v/calibration_model_manifest.json`
- `reports/stage03v/calibration_audit_sample.csv`

## Locked Dates

```text
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
historical_development: trade_date <= 2026-06-10
prospective_final_holdout: trade_date >= 2026-06-11
```

Stage03V reuses the Stage04 prospective validation ledger mechanism through a Stage03V-specific template export. It does not inherit Stage04's 2026-05-29 holdout start.

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-10 | Activated STAGE03V-WP0-v1 and blocked WP0.5 plus later packages until WP0 acceptance. | Codex |
| 2026-06-10 | Archived accepted WP0 and activated STAGE03V-WP0.5-v1 sample feasibility preflight. | ChatGPT |
| 2026-06-10 | Accepted STAGE03V-WP0.5-v1 sample feasibility preflight. | Codex |
| 2026-06-10 | Archived WP0.5 and activated STAGE03V-WP1-v1 risk event target dataset. | ChatGPT |
| 2026-06-10 | Accepted STAGE03V-WP1-v1 risk event target dataset builder. | Codex |
| 2026-06-10 | Archived WP1 and activated STAGE03V-WP2-v1 target controls gate. | ChatGPT |
| 2026-06-10 | Implemented STAGE03V-WP2-v1 target leakage, cross-cutoff, purge/embargo, and namespace control gate. | Codex |
| 2026-06-10 | Archived WP2 and activated STAGE03V-WP2.1-v1 full-target streaming audit. | ChatGPT |
| 2026-06-10 | Implemented STAGE03V-WP2.1-v1 full-target streaming / blockwise audit. | Codex |
| 2026-06-10 | Archived WP2.1 and activated STAGE03V-WP3-v1 baseline diagnostics. | ChatGPT |
| 2026-06-10 | Implemented STAGE03V-WP3-v1 volatility, range-based, empirical, and continuous diagnostic baselines. | Codex |
| 2026-06-11 | Archived accepted WP3 and activated STAGE03V-WP3.5-v1 volatility-scaled threshold sanity gate. | ChatGPT |
| 2026-06-11 | Implemented STAGE03V-WP3.5-v1 volatility-scaled threshold supplement and baseline metric sanity gate artifacts. | Codex |
| 2026-06-11 | Archived WP3.5 and activated STAGE03V-WP4-v1 logistic downside-risk hazard. | ChatGPT |
| 2026-06-11 | Implemented STAGE03V-WP4-v1 logistic downside-risk hazard artifacts and gate. | Codex |
| 2026-06-11 | Archived WP4 and activated STAGE03V-WP5-v1 calibration, clustered inference, and development-readiness. | ChatGPT |
| 2026-06-11 | Implemented STAGE03V-WP5-v1 calibration diagnostics, clustered inference, and development-readiness artifacts. | Codex |
