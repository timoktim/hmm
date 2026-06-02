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
| STAGE02-WP-D-v1 | 02 | D | archived | v1 | docs/work_packages/stage_02/STAGE02_WP_D_final_integration_acceptance.md | Codex Integration | accepted |

## Current Stage 02 Focus

Stage 02 is now in final acceptance.

Completed:

- WP-A: causal cache contract audit.
- WP-B: CI-safe validation and local DB artifact policy.
- WP-C: conservative readiness gate integration.

Active:

- WP-D: final Stage 02 integration summary and hard issue review.

Tracked risks carried forward:

- Causal cache rows exist but are not linked to the resolved HMM run id.
- Causal cache coverage is partial.
- Label alignment ambiguity remains high.
- CI does not use the private V0 DB.

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
| 2026-06-02 | Stage 02 WP-D final integration accepted Stage 02 with tracked risks. | Codex |
