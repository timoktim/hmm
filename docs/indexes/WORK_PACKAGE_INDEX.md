# WORK_PACKAGE_INDEX

Project: HMM / HSMM analyzer development
Repository: timoktim/hmm
Logical root: docs/

## Rules

1. Only rows with `status = active` are executable.
2. Archived or blocked rows must not be executed.
3. Codex must start from updated `main`.
4. Codex must read `docs/runtime/LOCAL_DB_HANDOFF.md` before any local DB-backed validation.
5. No Stage package may fetch external data or modify HMM/HSMM training algorithms unless a later data/model package explicitly allows it.
6. DuckDB and WAL files must not be committed.
7. Stage03R is hazard-first: HSMM stays lifecycle interpretation, Duration Hazard becomes the planned primary exit engine.

## Work Packages

| index_id | stage | wp | status | version | path | codex_thread | acceptance_status |
|---|---:|---|---|---|---|---|---|
| STAGE00-WP-A-v1 | 00 | A | archived | v1 | docs/work_packages/stage_00/STAGE00_WP_A_evidence_registry.md | Codex A | accepted |
| STAGE00-WP-B-v1 | 00 | B | archived | v1 | docs/work_packages/stage_00/STAGE00_WP_B_baseline_freeze.md | Codex B | accepted |
| STAGE00-WP-C-v1 | 00 | C | archived | v1 | docs/work_packages/stage_00/STAGE00_WP_C_ui_readiness_causal_boundary.md | Codex C | accepted |
| STAGE01-WP-A-v1 | 01 | A | archived | v1 | docs/work_packages/stage_01/STAGE01_WP_A_hmm_confidence_metrics.md | Codex A | accepted |
| STAGE01-WP-B-v1 | 01 | B | archived | v1 | docs/work_packages/stage_01/STAGE01_WP_B_hmm_label_alignment_stability.md | Codex B | accepted |
| STAGE01-WP-C-v1 | 01 | C | archived | v1 | docs/work_packages/stage_01/STAGE01_WP_C_hmm_churn_dwell_ui_readiness.md | Codex C | accepted |
| STAGE01-WP-D-v1 | 01 | D | archived | v1 | docs/work_packages/stage_01/STAGE01_WP_D_integration_summary_hard_review.md | Codex Integration | accepted |
| STAGE02-WP-A-v1 | 02 | A | archived | v1 | docs/work_packages/stage_02/STAGE02_WP_A_causal_cache_contract_audit.md | Codex A | accepted |
| STAGE02-WP-B-v1 | 02 | B | archived | v1 | docs/work_packages/stage_02/STAGE02_WP_B_ci_validation_artifact_skeleton.md | Codex B | accepted |
| STAGE02-WP-C-v1 | 02 | C | archived | v1 | docs/work_packages/stage_02/STAGE02_WP_C_readiness_gate_integration.md | Codex C | accepted |
| STAGE02-WP-D-v1 | 02 | D | blocked_until_wp_e | v1 | docs/work_packages/stage_02/STAGE02_WP_D_final_integration_acceptance.md | Codex Integration | pending |
| STAGE02-WP-E-v1 | 02 | E | active | v1 | docs/work_packages/stage_02/STAGE02_WP_E_causal_cache_lineage_repair.md | Codex Lineage | pending |
| STAGE03PF-WP0 | 03PF | WP0 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_00_BASELINE_AND_LINEAGE.md | Codex WP0 | accepted |
| STAGE03PF-WP1 | 03PF | WP1 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_00_BASELINE_AND_LINEAGE.md | Codex WP1 | accepted |
| STAGE03PF-WP2 | 03PF | WP2 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_01_HMM_CACHE_LINEAGE.md | Codex WP2 | accepted |
| STAGE03PF-WP3 | 03PF | WP3 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_01_HMM_CACHE_LINEAGE.md | Codex WP3 | accepted |
| STAGE03PF-WP4 | 03PF | WP4 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_02_HSMM_ASOF_ATOMICITY.md | Codex WP4 | accepted |
| STAGE03PF-WP5 | 03PF | WP5 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_02_HSMM_ASOF_ATOMICITY.md | Codex WP5 | accepted |
| STAGE03PF-WP6 | 03PF | WP6 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_02_HSMM_ASOF_ATOMICITY.md | Codex WP6 | accepted_by_pr38_gate |
| STAGE03PF-WP7 | 03PF | WP7 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_02_HSMM_ASOF_ATOMICITY.md | Codex WP7 | accepted_by_pr38_gate |
| STAGE03PF-WP8 | 03PF | WP8 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_03_READINESS_UI_UNIVERSE_EVIDENCE.md | Codex WP8 | accepted |
| STAGE03PF-WP9 | 03PF | WP9 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_03_READINESS_UI_UNIVERSE_EVIDENCE.md | Codex WP9 | accepted |
| STAGE03PF-WP10 | 03PF | WP10 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_03_READINESS_UI_UNIVERSE_EVIDENCE.md | Codex WP10 | accepted_by_pr38_gate |
| STAGE03PF-WP11 | 03PF | WP11 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_03_READINESS_UI_UNIVERSE_EVIDENCE.md | Codex WP11 | accepted |
| STAGE03PF-WP12 | 03PF | WP12 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_03_READINESS_UI_UNIVERSE_EVIDENCE.md | Codex WP12 | accepted_by_pr38_gate |
| STAGE03PF-WP13 | 03PF | WP13 | archived | v1 | docs/work_packages/stage03_preflight/STAGE03PF_BATCH_99_FINAL_GATE.md | Codex Gate | accepted_by_pr38_gate |
| STAGE03R-WP0 | 03R | WP0 | archived | v1 | docs/work_packages/stage03r/STAGE03R_WP0_scope_freeze_signal_contract.md | Codex Stage03R-WP0 | accepted |
| STAGE03R-WP1 | 03R | WP1 | archived | v1 | docs/work_packages/stage03r/STAGE03R_WP1_exit_target_dataset_v1.md | Codex Stage03R-WP1 | accepted |
| STAGE03R-WP2 | 03R | WP2 | archived | v1 | docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md | Codex Stage03R-WP2 | accepted |
| STAGE03R-WP3 | 03R | WP3 | archived | v1 | docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md | Codex Stage03R-WP3 | accepted |
| STAGE03R-WP4 | 03R | WP4 | archived | v1 | docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md | Codex Stage03R-WP4 | accepted |
| STAGE03R-WP5 | 03R | WP5 | active | v1 | docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md | Codex Stage03R-WP5 | pending |
| STAGE03R-WP6 | 03R | WP6 | blocked_until_wp5 | v1 | docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md | Codex Stage03R-WP6 | pending |
| STAGE03R-WP7 | 03R | WP7 | blocked_until_wp6 | v1 | docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md | Codex Stage03R-WP7 | pending |
| STAGE03R-WP8 | 03R | WP8 | blocked_until_wp6 | v1 | docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md | Codex Stage03R-WP8 | pending |

## Current Stage 03R Focus

Stage03 preflight passed via PR #38:

```text
Stage03PreflightVerdict: PASS
pytest -q: 400 passed, 2 skipped, 27 warnings
BlockingPackages: none
```

Active:

- STAGE03R-WP5: Isotonic Calibration.

Blocked until WP5:

- STAGE03R-WP6 hazard readiness matrix and later Duration Hazard packages.

## Future Stage03R Route

The route is hazard-first:

```text
Freeze HSMM as lifecycle interpretation layer
-> promote Duration Hazard as primary lifecycle exit engine
-> validate with risk/calibration/held-out discipline
-> default to ordinal tendency or abstain when support is insufficient
-> then move to low-cost break detection and simplified decision engine
```

Canonical documents:

```text
docs/roadmap/STAGE03R_ROUTE_ADJUSTMENT_20260603.md
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
docs/work_packages/stage03r/STAGE03R_WP0_scope_freeze_signal_contract.md
docs/work_packages/stage03r/STAGE03R_WP1_exit_target_dataset_v1.md
docs/work_packages/stage03r/STAGE03R_WP2_target_leakage_purge_tests.md
docs/work_packages/stage03r/STAGE03R_WP3_logistic_hazard_baseline.md
```

## Return Contract

Each Codex thread must report:

- index_id
- branch
- PR
- commands run
- local DB path or no-DB status
- generated reports
- external data fetch: no
- training algorithm modified: no
- DuckDB committed: no
- risks and unresolved issues

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-02 | Stage 02 WP-A/WP-B accepted and WP-C activated. | ChatGPT |
| 2026-06-02 | Stage 02 WP-C accepted and WP-D final acceptance activated. | ChatGPT |
| 2026-06-02 | Stage 02 final acceptance paused; WP-E causal cache lineage repair activated. | ChatGPT |
| 2026-06-03 | Stage03 preflight WP13 gate recorded BLOCKED verdict and reopened WP6/WP7/WP10/WP12. | ChatGPT |
| 2026-06-03 | Recorded Stage03R hazard-first route as future direction, blocked until Stage03 preflight pass. | ChatGPT |
| 2026-06-03 | PR #38 passed Stage03 preflight gate; activated Stage03R WP0. | ChatGPT |
| 2026-06-04 | PR #39 merged WP0 scope freeze; activated Stage03R WP1 exit target dataset. | ChatGPT |
| 2026-06-04 | PR #40 merged WP1 exit target dataset; activated Stage03R WP2 target leakage/purge tests. | ChatGPT |
| 2026-06-04 | PR #41 merged WP2 target leakage/purge tests; activated Stage03R WP3 logistic hazard baseline. | ChatGPT |
| 2026-06-04 | PR #42 merged WP3 logistic hazard baseline; activated Stage03R WP4 age-bucket baseline. | ChatGPT |
| 2026-06-04 | PR #43 merged WP4 age-bucket baseline; activated Stage03R WP5 isotonic calibration. | ChatGPT |
