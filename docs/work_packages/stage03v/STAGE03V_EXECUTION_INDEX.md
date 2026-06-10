# STAGE03V_EXECUTION_INDEX

Status: active
Stage: 03V / Volatility and downside-risk hazard
Active package: STAGE03V-WP0-v1

## Purpose

Stage03V defines a volatility and downside-risk hazard route after the Stage03R
hazard-first lifecycle work and Stage04 prospective validation discipline. WP0
freezes the scope, contracts, taxonomy, readiness policy, and prospective
holdout registration before any target building, model training, probability
calibration, or empirical holdout consumption.

## Route Anchors

- `docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md`
- `docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md`
- `docs/work_packages/stage03v/STAGE03V_WP0_scope_freeze_contracts_ledger.md`
- `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP0_scope_freeze_contracts_ledger.md`

## Package Sequence

| index_id | package | status | branch | purpose |
|---|---|---|---|---|
| STAGE03V-WP0-v1 | Scope Freeze, Contracts, Ledger | active | stage03v/wp0-scope-freeze-contracts-ledger | freeze Stage03V scope, signal contract, readiness policy, SW2021 L2 universe, and Stage03V holdout registration |
| STAGE03V-WP0.5 | Sample Feasibility Preflight | blocked_until_wp0_accepted | pending | count feasibility evidence only after WP0 contracts are accepted |
| STAGE03V-WP1 | Risk Event Target Dataset v1 | blocked_until_wp0_5_accepted | pending | build target dataset after feasibility gate |
| STAGE03V-WP2 | Target Leakage, Purge, Embargo, and CI Gate | blocked | pending | enforce target leakage controls after target dataset exists |
| STAGE03V-WP3 | Volatility, Range-Based, Empirical, and Continuous Diagnostic Baselines | blocked | pending | add baseline diagnostics after target controls exist |
| STAGE03V-WP3.5 | Volatility-Scaled Threshold Supplement | blocked | pending | evaluate volatility-scaled threshold supplement before readiness promotion |
| STAGE03V-WP4 | Logistic Downside Risk Hazard v1 | blocked | pending | train downside risk hazard only after prior contracts and gates pass |
| STAGE03V-WP5 | Calibration, Clustered Inference, and Downside Risk Readiness Matrix | blocked | pending | calibrate and assign readiness only after model validation artifacts exist |
| STAGE03V-WP6 | Risk Validation Protocol and Downshift Research Report | blocked | pending | validate research-only/downshift evidence after readiness matrix |
| STAGE03V-WP7 | Stage03V1 Final Gate | blocked | pending | produce final Stage03V1 gate after all prior packages are accepted |

## Execution Rules

1. Only STAGE03V-WP0-v1 is executable in this branch.
2. STAGE03V-WP0.5 and all later packages are blocked until WP0 is accepted.
3. WP0 must not build `risk_event_target_dataset_v1`.
4. WP0 must not read or write DuckDB target tables.
5. WP0 must not fetch external data.
6. WP0 must not train logistic hazard, volatility baseline, HAR diagnostic, calibration, readiness matrix, or downshift validation models.
7. WP0 must not consume or inspect prospective final holdout performance.
8. WP0 must not modify HMM or HSMM training algorithms.
9. WP0 must not create UI, decision, trading, buy/sell, recommendation, or sizing outputs.
10. Stage03V2 and Stage03V3 remain placeholders only unless a later reviewed package explicitly activates them.

## WP0 Deliverables

- `configs/risk_event_signal_contract_v1.yaml`
- `configs/readiness_policy_risk_event_v1.yaml`
- `configs/stage03v_sw_l2_universe_manifest_v1.yaml`
- `reports/stage04/prospective_validation_ledger.stage03v.template.jsonl`
- `reports/stage03v/stage03v_wp0_scope_freeze_report.md`
- `reports/stage03v/stage03v_wp0_scope_freeze_report.json`
- `tests/test_stage03v_contracts.py`

## Locked Dates

```text
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
historical_development: trade_date <= 2026-06-10
prospective_final_holdout: trade_date >= 2026-06-11
```

Stage03V reuses the Stage04 prospective validation ledger mechanism through a
Stage03V-specific template export. It does not inherit Stage04's 2026-05-29
holdout start.

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-10 | Activated STAGE03V-WP0-v1 and blocked WP0.5 plus later packages until WP0 acceptance. | Codex |
