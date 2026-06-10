# STAGE03V_EXECUTION_INDEX

Status: active
Stage: 03V / Volatility and downside-risk hazard
Active package: STAGE03V-WP2-v1

## Purpose

Stage03V defines a volatility and downside-risk hazard route after the Stage03R hazard-first lifecycle work and Stage04 prospective validation discipline. WP0 froze the scope, contracts, taxonomy, readiness policy, and prospective holdout registration before any target building, model training, probability calibration, or empirical holdout consumption.

WP0.5 completed sample-feasibility preflight on the V7 verified SW2021 L2 universe. WP1 completed the first formal Stage03V1 downside-risk target dataset builder and synthetic path-target tests. WP2 is now active and creates the target-control gate for target leakage, permanent cross-cutoff censoring, purge/embargo, and feature/target namespace leakage policy.

## Route Anchors

- `docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md`
- `docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md`
- `docs/work_packages/stage03v/STAGE03V_WP0_scope_freeze_contracts_ledger.md`
- `docs/work_packages/stage03v/STAGE03V_WP0.5_sample_feasibility_preflight.md`
- `docs/work_packages/stage03v/STAGE03V_WP1_risk_event_target_dataset_v1.md`
- `docs/work_packages/stage03v/STAGE03V_WP2_target_leakage_purge_embargo_ci_gate.md`
- `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP2_target_leakage_purge_embargo_ci_gate.md`
- `reports/stage03v/sample_feasibility_report.json`
- `reports/stage03v/risk_event_target_support.json`

## Package Sequence

| index_id | package | status | branch | purpose |
|---|---|---|---|---|
| STAGE03V-WP0-v1 | Scope Freeze, Contracts, Ledger | archived | stage03v/wp0-scope-freeze-contracts-ledger | freeze Stage03V scope, signal contract, readiness policy, SW2021 L2 universe, and Stage03V holdout registration |
| STAGE03V-WP0.5-v1 | Sample Feasibility Preflight | archived | stage03v/wp0.5-sample-feasibility-preflight | count downside-risk event feasibility evidence before target dataset construction |
| STAGE03V-WP1-v1 | Risk Event Target Dataset v1 | archived | stage03v/wp1-risk-event-target-dataset-v1 | build formal downside-risk target dataset builder and synthetic path-target tests |
| STAGE03V-WP2-v1 | Target Leakage, Purge, Embargo, and CI Gate | active | stage03v/wp2-target-leakage-purge-embargo-ci-gate | enforce target controls before baseline or model packages open |
| STAGE03V-WP3 | Volatility, Range-Based, Empirical, and Continuous Diagnostic Baselines | blocked_until_wp2_accepted | pending | add baseline diagnostics after target controls exist |
| STAGE03V-WP3.5 | Volatility-Scaled Threshold Supplement | blocked | pending | evaluate volatility-scaled threshold supplement before readiness promotion |
| STAGE03V-WP4 | Logistic Downside Risk Hazard v1 | blocked | pending | train downside risk hazard only after prior contracts and gates pass |
| STAGE03V-WP5 | Calibration, Clustered Inference, and Downside Risk Readiness Matrix | blocked | pending | calibrate and assign readiness only after model validation artifacts exist |
| STAGE03V-WP6 | Risk Validation Protocol and Downshift Research Report | blocked | pending | validate research-only/downshift evidence after readiness matrix |
| STAGE03V-WP7 | Stage03V1 Final Gate | blocked | pending | produce final Stage03V1 gate after all prior packages are accepted |

## Execution Rules

1. Only STAGE03V-WP2-v1 is executable in the current Stage03V branch sequence.
2. STAGE03V-WP3 and later packages are blocked until WP2 is accepted.
3. WP2 must use the V7 DB path and accepted WP1 target support artifacts as hard inputs.
4. WP2 may rebuild or audit target rows in memory, but must not modify the target dataset.
5. WP2 must not train any model.
6. WP2 must not assign `usable_probability`, `ordinal_only`, or any model readiness status.
7. WP2 must not fetch external data.
8. WP2 must not consume or inspect prospective final holdout performance.
9. WP2 must enforce permanent cross-cutoff censoring and prove append-future-prices rows are not backfilled.
10. WP2 must create deterministic purge/embargo fold-policy artifacts without training a model.
11. WP2 must create feature/target namespace leakage policy artifacts for later feature packages.
12. WP2 must not modify HMM or HSMM training algorithms.
13. WP2 must not create UI, trading, buy/sell, recommendation, sizing, or decision outputs.
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

## WP2 Expected Deliverables

- `src/evaluation/stage03v_target_controls.py`
- `scripts/stage03v_target_controls_gate.sh`
- `tests/test_stage03v_target_controls.py`
- `tests/test_stage03v_purge_embargo.py`
- `configs/stage03v_purge_embargo_policy_v1.yaml`
- `reports/stage03v/target_controls_report.md`
- `reports/stage03v/target_controls_report.json`
- `reports/stage03v/purge_embargo_fold_plan.json`
- `reports/stage03v/target_controls_audit_sample.csv`

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
