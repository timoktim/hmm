# STAGE00_RECOVERY_COORDINATION

Date: 2026-06-01
Repository: timoktim/hmm
Current coordination status: recovery / bootstrap alignment

## What happened

The GitHub repository was initially empty except for planning documents. Stage 00 work packages assumed that the V0 starting model already existed in the repository. Because the V0 source was not yet present, the first Codex thread could not find the correct starting point.

The WP-A thread then synced the local V0 source into branch:

```text
stage00/wp-a-evidence-registry
```

That branch opened PR #1:

```text
https://github.com/timoktim/hmm/pull/1
```

PR #1 now has two meanings:

1. Bootstrap import of the V0 baseline source code into GitHub.
2. Implementation of `STAGE00-WP-A-v1` evidence registry.

This is acceptable as a recovery step, but it must be documented clearly. WP-B and WP-C should not pretend that main already contains the V0 baseline until PR #1 is merged.

## Where the V0 source currently is

Current valid V0 source location:

```text
branch: stage00/wp-a-evidence-registry
root: repository root
```

Expected source layout on that branch:

```text
app.py
src/
  data_pipeline/
  data_sources/
  evaluation/
  features/
  models/
  scoring/
  ui/
  utils/
tests/
reports/evidence_registry/
requirements.txt
pyproject.toml
*.command
*.md
```

This layout is correct. Do not move `app.py`, `src/`, or `tests/` into a nested folder. The correct project root is the repository root.

Runtime artifacts must remain excluded:

```text
data/db/*.duckdb
data/cache/
data/logs/
data/models/
.venv/
*.zip
```

## Recommended recovery sequence

Preferred sequence:

1. WP-A thread cleans up PR #1 title/body and confirms tests.
2. Reviewer accepts PR #1 as `bootstrap + WP-A` if it passes.
3. Merge PR #1 into `main`.
4. WP-B and WP-C start from updated `main`, not from the old empty main.

Temporary parallel option:

- WP-B and WP-C may inspect the V0 source from `stage00/wp-a-evidence-registry`, but they should not open final PRs to `main` until PR #1 is merged.
- If they must work before merge, they should branch from `stage00/wp-a-evidence-registry` and clearly mark their PRs as stacked on PR #1.

## Stage 00 boundaries remain unchanged

Stage 00 must not:

- fetch new market or constituent data;
- modify HMM/HSMM training algorithms;
- promote HMM/HSMM probability outputs to trading signals;
- mix in-sample states with causal walk-forward states;
- expose numeric HSMM `p_exit` without readiness gating.

## Current active work packages

Authoritative index:

```text
docs/indexes/WORK_PACKAGE_INDEX.md
```

Active packages:

```text
docs/work_packages/stage_00/STAGE00_WP_A_evidence_registry.md
docs/work_packages/stage_00/STAGE00_WP_B_baseline_freeze.md
docs/work_packages/stage_00/STAGE00_WP_C_ui_readiness_causal_boundary.md
```

## Recovery decision

The V0 source imported by WP-A is in the correct repository root layout. The issue is not file placement. The issue is branch coordination: main does not yet contain the V0 baseline until PR #1 is merged.
