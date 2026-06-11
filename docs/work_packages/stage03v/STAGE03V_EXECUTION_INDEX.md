# STAGE03V_EXECUTION_INDEX

Status: active
Stage: 03V / Volatility and downside-risk hazard
Active package: STAGE03V-WP7-v1

## Purpose

Stage03V defines a volatility and downside-risk hazard route after the Stage03R hazard-first lifecycle work and Stage04 prospective validation discipline. WP0 froze the scope, contracts, taxonomy, readiness policy, and prospective holdout registration before any target building, model training, probability calibration, or empirical holdout consumption.

WP0.5 completed sample-feasibility preflight on the V7 verified SW2021 L2 universe. WP1 completed the first formal Stage03V1 downside-risk target dataset builder and synthetic path-target tests. WP2 created the target-control gate for target leakage, permanent cross-cutoff censoring, purge/embargo, and feature/target namespace leakage policy. WP2.1 completed a full-target streaming / blockwise audit. WP3 completed causal baseline diagnostics. WP3.5 completed volatility-scaled threshold supplement and baseline metric sanity checks. WP4 completed logistic downside-risk hazard v1. WP5 completed calibration diagnostics, clustered inference, and development-only downside-risk readiness. WP6 completed historical-development risk validation protocol and research-only downshift evidence pack. WP7 is now active and produces the final Stage03V1 gate verdict.

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
- `docs/work_packages/stage03v/STAGE03V_WP7_stage03v1_final_gate.md`
- `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP7_stage03v1_final_gate.md`
- `configs/risk_event_signal_contract_v1.yaml`
- `configs/readiness_policy_risk_event_v1.yaml`
- `configs/stage03v_sw_l2_target_universe_v1.yaml`
- `configs/stage03v_purge_embargo_policy_v1.yaml`
- `configs/stage03v_logistic_hazard_policy_v1.yaml`
- `configs/stage03v_calibration_readiness_policy_v1.yaml`
- `configs/stage03v_risk_validation_protocol_policy_v1.yaml`
- `configs/stage03v_final_gate_policy_v1.yaml`
- `reports/stage04/prospective_validation_ledger.stage03v.template.jsonl`
- `reports/stage03v/stage03v_wp0_scope_freeze_report.json`
- `reports/stage03v/sample_feasibility_report.json`
- `reports/stage03v/risk_event_target_support.json`
- `reports/stage03v/target_controls_report.json`
- `reports/stage03v/full_target_streaming_audit_report.json`
- `reports/stage03v/baseline_diagnostics_report.json`
- `reports/stage03v/vol_scaled_threshold_sanity_report.json`
- `reports/stage03v/logistic_hazard_report.json`
- `reports/stage03v/calibration_readiness_report.json`
- `reports/stage03v/risk_validation_report.json`
- `reports/stage03v/downshift_research_report.json`
- `reports/stage03v/wp7_final_gate_input_manifest.json`

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
| STAGE03V-WP5-v1 | Calibration, Clustered Inference, and Downside Risk Readiness Matrix | archived | stage03v/wp5-calibration-clustered-readiness | calibrate logistic hazard outputs and assign development-only readiness after WP4 acceptance |
| STAGE03V-WP6-v1 | Risk Validation Protocol and Downshift Research Report | archived | stage03v/wp6-risk-validation-downshift-report | validate historical-development research-only/downshift evidence after readiness matrix |
| STAGE03V-WP7 | Stage03V1 Final Gate | active | stage03v/wp7-stage03v1-final-gate | produce final Stage03V1 gate verdict after all prior packages are accepted |

## Execution Rules

1. Only STAGE03V-WP7-v1 is executable in the current Stage03V branch sequence.
2. WP7 may read only WP0-WP6 artifacts and verify consistency, evidence sufficiency, and boundary adherence.
3. WP7 must not train models, recalibrate probabilities, reassign readiness, or consume prospective holdout unless explicitly authorized.
4. WP7 must produce final Stage03V1 gate report, verdict JSON, evidence matrix, artifact manifest, post-gate action plan, and audit sample.
5. WP7 must preserve fixed-threshold Stage03V1 target mainline and treat WP3.5 volatility-scaled candidates as reference only.
6. WP7 may emit a defer verdict if prospective holdout requirements are not met.
7. Stage03V2 and Stage03V3 remain placeholders.
