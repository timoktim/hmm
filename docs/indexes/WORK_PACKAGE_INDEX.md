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
5. Stage 01 must start from updated `main`, must not fetch external data by default, and must not modify HMM/HSMM training algorithms.

## Work Packages

| index_id | stage | wp | status | version | path | codex_thread | acceptance_status |
|---|---:|---|---|---|---|---|---|
| STAGE00-WP-A-v1 | 00 | A | archived | v1 | docs/work_packages/stage_00/STAGE00_WP_A_evidence_registry.md | Codex A | accepted |
| STAGE00-WP-B-v1 | 00 | B | archived | v1 | docs/work_packages/stage_00/STAGE00_WP_B_baseline_freeze.md | Codex B | accepted |
| STAGE00-WP-C-v1 | 00 | C | archived | v1 | docs/work_packages/stage_00/STAGE00_WP_C_ui_readiness_causal_boundary.md | Codex C | accepted |
| STAGE01-WP-A-v1 | 01 | A | active | v1 | docs/work_packages/stage_01/STAGE01_WP_A_hmm_confidence_metrics.md | Codex A | pending |
| STAGE01-WP-B-v1 | 01 | B | active | v1 | docs/work_packages/stage_01/STAGE01_WP_B_hmm_label_alignment_stability.md | Codex B | pending |
| STAGE01-WP-C-v1 | 01 | C | active | v1 | docs/work_packages/stage_01/STAGE01_WP_C_hmm_churn_dwell_ui_readiness.md | Codex C | pending |

## Stage 00 Boundary

Stage 00 is closed. It was limited to freezing the current baseline and establishing evidence/readiness infrastructure.

- WP-A: evidence registry, validation run registry, artifact manifest, UI readiness policy schema and seed.
- WP-B: baseline freeze, DB inventory, run inventory, report inventory, current HMM/HSMM/UI boundary snapshot.
- WP-C: UI readiness gate, causal vs in-sample boundary, probability display restrictions, text policy audit.

## Stage 01 Boundary

Stage 01 is limited to HMM baseline strengthening. It must improve interpretability, stability diagnostics, and readiness behavior around the existing HMM outputs.

Stage 01 may:

- compute HMM posterior confidence metrics;
- audit label alignment and state identity stability;
- compute churn/dwell metrics;
- add conservative UI readiness warnings or downgrades.

Stage 01 must not:

- implement Robust HMM, Sticky HMM, Student-t emissions, or new training algorithms;
- modify HSMM training or HSMM lifecycle semantics;
- implement duration hazard, BOCPD, or decision engine;
- fetch external market or constituent data unless a later explicit data work package is opened.

## Codex Retrieval Instruction

Codex should:

1. Open this index.
2. Find the assigned index_id.
3. Confirm status = active.
4. Open the referenced path.
5. Execute the package on a dedicated branch.
6. Return results using the package-specific return contract.

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
- external data fetch: must be no for Stage 01
- training algorithm modified: must be no for Stage 01
- risks and unresolved issues
- acceptance focus

## Archive Policy

Do not rely on deleting files. When a new version is created, change the old row status to superseded. When a package is accepted, change acceptance_status to accepted and optionally move the package status to archived after the stage closes.

## Revision Log

| date | change | by |
|---|---|---|
| 2026-06-01 | Created GitHub-based Stage 00 work package index. | ChatGPT |
| 2026-06-01 | Archived accepted Stage 00 packages and activated Stage 01 WP-A/WP-B/WP-C. | ChatGPT |
