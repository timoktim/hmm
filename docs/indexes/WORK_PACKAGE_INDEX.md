# WORK_PACKAGE_INDEX

Project: HMM / HSMM analyzer development
Repository: timoktim/hmm
Logical root: docs/
Created: 2026-06-01

This file is the authoritative work-package index for Codex. Google Drive may still contain reference copies, but Codex should use this repository index and the Markdown files under docs/work_packages/ as the primary source.

## Rules

1. Only rows with status = active are executable.
2. Superseded, archived, obsolete, or probe files must not be executed.
3. Each stage/WP pair should have only one active version.
4. Codex must report the index_id, file path, version, branch, commands run, test results, generated reports, data usage, and unresolved risks.
5. Stage 02 must start from updated `main`, must not fetch external data by default, and must not modify HMM/HSMM training algorithms.
6. Any task that needs V0 local data must read `docs/runtime/LOCAL_DB_HANDOFF.md` first and run its local DB preflight check.

## Local DB Protocol

The V0 DuckDB database is not stored in GitHub. Data-backed validation must use either:

```text
data/db/a_share_hmm.duckdb
```

or an explicit environment override:

```bash
export ASHARE_HMM_DB_PATH=/absolute/path/to/a_share_hmm.duckdb
```

Codex must not commit DuckDB or WAL files. Missing DB is a blocking condition for data-backed validation and should be reported as `local_db_missing`, not silently treated as pass.

Canonical instructions:

```text
docs/runtime/LOCAL_DB_HANDOFF.md
```

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
| STAGE02-WP-A-v1 | 02 | A | active | v1 | docs/work_packages/stage_02/STAGE02_WP_A_causal_cache_contract_audit.md | Codex A | pending |
| STAGE02-WP-B-v1 | 02 | B | active | v1 | docs/work_packages/stage_02/STAGE02_WP_B_ci_validation_artifact_skeleton.md | Codex B | pending |
| STAGE02-WP-C-v1 | 02 | C | blocked_until_wp_a_wp_b | v1 | docs/work_packages/stage_02/STAGE02_WP_C_readiness_gate_integration.md | Codex C | pending |

## Stage 00 Boundary

Stage 00 is closed. It was limited to freezing the current baseline and establishing evidence/readiness infrastructure.

- WP-A: evidence registry, validation run registry, artifact manifest, UI readiness policy schema and seed.
- WP-B: baseline freeze, DB inventory, run inventory, report inventory, current HMM/HSMM/UI boundary snapshot.
- WP-C: UI readiness gate, causal vs in-sample boundary, probability display restrictions, text policy audit.

## Stage 01 Boundary

Stage 01 is closed. It strengthened HMM baseline diagnostics without changing training algorithms.

- WP-A: HMM posterior confidence diagnostics.
- WP-B: HMM label alignment and state identity stability.
- WP-C: HMM churn/dwell diagnostics and readiness downgrade.
- WP-D: final integration summary and hard-issue review.

Stage 01 final verdict: `Stage01PassWithTrackedRisks`.

Tracked risks carried into Stage 02:

- No GitHub Actions CI.
- Causal cache unavailable, so readiness remains `research_only`.
- Label alignment ambiguity is high.
- Diagnostics rely on local V0 DB validation rather than CI-managed DB artifact.

## Stage 02 Boundary

Stage 02 is limited to causal evidence and reproducible validation gates.

Stage 02 may:

- audit causal walk-forward cache availability and metadata;
- add CI-safe validation artifacts that do not require private DB;
- aggregate readiness from confidence, label alignment, churn/dwell, causal cache, and CI evidence;
- document why readiness remains conservative.

Stage 02 must not:

- implement Robust HMM, Sticky HMM, Student-t emissions, or new training algorithms;
- modify HSMM training or HSMM lifecycle semantics;
- implement duration hazard, BOCPD, or decision engine;
- fetch external market or constituent data unless a later explicit data work package is opened;
- mark any HMM output as decision-ready.

## Codex Retrieval Instruction

Codex should:

1. Open this index.
2. Find the assigned index_id.
3. Confirm status = active.
4. Open the referenced path.
5. If the task needs local V0 data, read `docs/runtime/LOCAL_DB_HANDOFF.md` and run the DB preflight check.
6. Execute the package on a dedicated branch.
7. Return results using the package-specific return contract.

## Return Contract

Each Codex thread must return:

- index_id
- path
- version
- branch
- status: pass / partial / fail
- modified files
- new files
- commands run
- test results
- generated reports
- local DB usage: yes/no
- local DB path used: required for data-backed validation
- local DB preflight result: required for data-backed validation
- external data fetch: must be no for Stage 02
- training algorithm modified: must be no for Stage 02
- risks and unresolved issues
- acceptance focus

## Archive Policy

Do not rely on deleting files. When a new version is created, change the old row status to superseded. When a package is accepted, change acceptance_status to accepted and optionally move the package status to archived after the stage closes.

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-01 | Created GitHub-based Stage 00 work package index. | ChatGPT |
| 2026-06-01 | Added Stage 01 work packages and boundaries. | Codex |
| 2026-06-02 | Added local DB handoff protocol reference. | ChatGPT |
| 2026-06-02 | Added Stage 01 WP-D integration summary and hard review work package. | ChatGPT |
| 2026-06-02 | WP-D integration review accepted Stage 01 WP-A/WP-B/WP-C with tracked risks. | Codex |
| 2026-06-02 | Registered Stage 02 WP-A/WP-B/WP-C work packages. | ChatGPT |
