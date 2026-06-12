# STAGE03V_EXECUTION_INDEX

Status: active
Stage: 03V / Volatility and downside-risk hazard
Active package: STAGE03V-PHASE2-WP0-v1 (implemented_pending_acceptance)

## Audit Notice and RERUN1 Supersession

The Stage03V1 post-completion audit found that the original WP2 fold plan used by WP4-WP6 covered only a 2014 micro-window from the WP2 audit sample. The old WP4-WP6 empirical outputs were therefore invalidated as evidence of signal strength or weakness, although their engineering and boundary discipline remained useful.

FIX1 archived the contract repairs. RERUN1 archived the full-scale revalidation: fold plan v2 magnitude gate, WP4 logistic rerun, WP5 calibration/readiness rerun, and B2 three-arm downshift experiment. PR89 merged RERUN1. PR90 merged WP7-v2, producing the accepted Stage03V1 final gate v2 verdict. PR91 merged CLOSEOUT1, freezing the phase-one artifact set, invalidated-artifact rules, final interpretation, and Phase 2 handoff.

WP7-v1 is superseded/closed. WP7-v2 uses RERUN1 artifacts and does not use the old WP6 tier aggregation outputs as final evidence. CLOSEOUT1 freezes the accepted WP7-v2 interpretation. Stage03V Phase 2 is baseline-first and starts with a read-only research signal panel.

## Purpose

Stage03V defines a volatility and downside-risk hazard route after Stage03R and Stage04 validation discipline. Stage03V1 built and audited downside-risk event targets, causal baselines, logistic hazard, calibration/readiness, and historical-development risk-validation evidence. RERUN1 replaced invalidated microfold evidence with full-scale validation. WP7-v2 produced the final Stage03V1 first-phase verdict:

```text
PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE
```

Stage03V Phase 2 proceeds from the accepted closeout interpretation:

```text
primary_direction: baseline_first_risk_control_architecture
primary_baseline_family: realized_volatility
model_role: research_only_hazard_overlay
HMM_HSMM_role: context_only
prospective_holdout_role: future_authorized_quarterly_review_only
trading_or_decision_output: no
```

PHASE2-WP0 creates the first read-only signal panel contract, snapshot adapter, and UI page. It must organize existing validated signals for human review and must not create trading, sizing, recommendation, or execution outputs.

## Route Anchors

- `docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md`
- `docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md`
- `docs/roadmap/STAGE03V_PHASE1_CLOSEOUT_AND_PHASE2_HANDOFF.md`
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
- `docs/work_packages/stage03v/STAGE03V_WP7_v2_stage03v1_final_gate_rerun1.md`
- `docs/work_packages/stage03v/STAGE03V_CLOSEOUT1_artifact_freeze.md`
- `docs/work_packages/stage03v/STAGE03V_PHASE2_WP0_signal_panel_contract.md`
- `docs/codex_instructions/stage03v/CODEX_STAGE03V_PHASE2_WP0_signal_panel_contract.md`
- `reports/stage03v/stage03v1_phase1_closeout_report.json`
- `reports/stage03v/stage03v1_phase2_handoff.json`
- `reports/stage03v/stage03v1_artifact_freeze_manifest.json`
- `reports/stage03v/stage03v1_invalidated_artifact_registry.json`
- `reports/stage03v/stage03v1_final_gate_v2_report.json`
- `reports/stage03v/calibration_readiness_report.json`
- `reports/stage03v/downside_readiness_matrix.csv`
- `reports/stage03v/downshift_experiment_report.json`

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
| STAGE03V-WP7-v2 | Stage03V1 Final Gate after RERUN1 | archived | stage03v/wp7-v2-stage03v1-final-gate-rerun1 | accepted final gate verdict using RERUN1 artifacts, expanded B2 verdict states, and registered holdout thresholds |
| STAGE03V-CLOSEOUT1-v1 | Stage03V1 Phase 1 Closeout and Artifact Freeze | archived | stage03v/closeout1-artifact-freeze | freeze accepted Stage03V1 Phase 1 artifacts, invalidated-artifact rules, final interpretation, and Phase 2 handoff |
| STAGE03V-PHASE2-WP0-v1 | Signal Panel Contract and Snapshot | implemented_pending_acceptance | stage03v/phase2-wp0-signal-panel-contract | add read-only signal panel contract, snapshot adapter, and UI page for baseline-first human review |
| STAGE03V-PHASE2-WP1 | Volatility Baseline Risk Overlay Artifact | blocked_until_phase2_wp0_accepted | TBD | harden baseline volatility overlay after signal panel contract is accepted |
| STAGE03V-PHASE2-WP2 | Hazard-as-Overlay Residual Research | blocked_until_phase2_wp1 | TBD | evaluate hazard as research-only overlay rather than primary downshift driver |
| STAGE03V-PHASE2-WP3 | Prospective Holdout Ledger and Quarterly Review Harness | blocked_until_authorized_holdout_review | TBD | future authorized holdout review only after registered thresholds are met |
| STAGE03V-PHASE2-WP4 | Research Console / Casebook Integration | blocked_until_approved_research_interface_scope | TBD | integrate accepted research signals into casebook/human review flow |

## Execution Rules

1. STAGE03V-PHASE2-WP0-v1 is implemented pending acceptance; Phase 2 WP1 remains blocked until WP0 is accepted.
2. PHASE2-WP0 must add a read-only `信号面板` under `当前状态`.
3. PHASE2-WP0 must use baseline volatility signals as the primary risk layer.
4. HMM state and HSMM lifecycle signals are context only.
5. Stage03V calibrated probabilities may be displayed only when an actual current per-entity calibrated score source exists; otherwise the panel must show `unavailable_current_per_entity_score_source`.
6. Invalidated pre-RERUN1 WP4-WP6 and old WP7-v1 artifacts must not be used as signal sources.
7. PHASE2-WP0 must not train models, recalibrate probabilities, reassign readiness, consume prospective holdout, or implement Stage03V2/3.
8. PHASE2-WP0 must not create trading, buy/sell, sizing, recommendation, execution, portfolio-action, or UI decision outputs.

## PHASE2-WP0 Expected Deliverables

- `src/signals/signal_panel_snapshot.py`
- `src/ui/signal_panel_page.py`
- `tests/test_signal_panel_snapshot.py`
- `tests/test_signal_panel_ui_contract.py`
- `docs/runtime/STAGE03V_SIGNAL_PANEL_CONTRACT.md`
- `reports/stage03v/phase2_signal_panel_contract.json`
- navigation/app wiring for `当前状态 / 信号面板`

## Locked Dates and Holdout Requirement

```text
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
prospective_holdout_min_complete_20d_label_trade_dates: 120
prospective_holdout_min_market_event_blocks: 2
```

The 120 / 2 holdout minimum remains registered and must not be silently relaxed.

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-10 | Activated STAGE03V-WP0-v1 and blocked WP0.5 plus later packages until WP0 acceptance. | Codex |
| 2026-06-10 | Accepted STAGE03V-WP0.5-v1 sample feasibility preflight. | Codex |
| 2026-06-10 | Implemented WP1-WP3 baseline/target/control packages. | Codex |
| 2026-06-11 | Implemented WP3.5-WP6 original packages; later empirical evidence invalidated by microfold audit. | Codex |
| 2026-06-12 | Implemented FIX1 and accepted RERUN1 full-scale revalidation in PR89. | Codex |
| 2026-06-12 | Implemented STAGE03V-WP7-v2 final gate artifacts with baseline-superior primary-risk verdict and registered 120/2 holdout thresholds. | Codex |
| 2026-06-12 | Implemented STAGE03V-CLOSEOUT1-v1 artifact freeze, invalidated-artifact registry, and Phase 2 baseline-first handoff. | Codex |
| 2026-06-12 | Activated STAGE03V-PHASE2-WP0-v1 signal panel contract and snapshot package. | ChatGPT |
| 2026-06-12 | Implemented STAGE03V-PHASE2-WP0-v1 read-only signal panel, snapshot adapter, contract report, and navigation wiring. | Codex |
