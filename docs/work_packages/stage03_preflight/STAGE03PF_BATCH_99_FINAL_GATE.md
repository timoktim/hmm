# STAGE03PF_BATCH_99_FINAL_GATE

Purpose: close Stage03 preflight hardening and decide whether true Stage03 work can begin.

This file contains:

- WP13 Stage03 Preflight Gate

Do not implement Duration Hazard, BOCPD, Decision Engine, Robust HMM, Sticky HMM, or any new model work in this package.

## Dependency

Run this only after required preflight packages are accepted:

```text
P0 required: WP0, WP1, WP2, WP3, WP4, WP6, WP7
P1 required or explicitly accepted: WP8, WP9, WP10, WP11
P1 recommended: WP5
P2/P3 optional: WP12
```

WP12 may be deferred only if the final verdict explicitly records the deferral and no UI exposure depends on it.

## Branch

```text
stage03pf/wp13-stage03-preflight-gate
```

Start from updated `main`:

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage03pf/wp13-stage03-preflight-gate
```

## Allowed files

```text
scripts/stage03_preflight_gate.sh
reports/stage03_preflight/preflight_verdict.md
reports/stage03_preflight/preflight_verdict.json
docs/indexes/WORK_PACKAGE_INDEX.md
```

Do not modify source code.

## Required gate script

Create `scripts/stage03_preflight_gate.sh` that runs:

```bash
python -m compileall -q src tests
pytest -q \
  tests/test_lineage_hash_contract.py \
  tests/test_hmm_walk_forward_cache_contract.py \
  tests/test_hmm_cached_state_feature_guard.py \
  tests/test_hsmm_lifecycle_asof_targets.py \
  tests/test_hsmm_duration_tail_semantics.py \
  tests/test_hsmm_prefix_causality.py \
  tests/test_hsmm_run_atomicity.py \
  tests/test_hsmm_cascade_cleanup.py \
  tests/test_probability_readiness_lineage.py \
  tests/test_probability_gate_strictness.py \
  tests/test_ui_readiness_selection.py \
  tests/test_analysis_cache_selection.py \
  tests/test_universe_data_lineage.py \
  tests/test_evidence_registry_contract.py
```

Also run:

```bash
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

If `python` or `pytest` is unavailable, support `.venv/bin/python` and `.venv/bin/pytest` and report the fallback. Do not hide failures.

## Required verdict report

Create:

```text
reports/stage03_preflight/preflight_verdict.md
reports/stage03_preflight/preflight_verdict.json
```

The report must include:

```text
P0 package status
P1 package status
P2/P3 package status
legacy/debug cache status
HMM cache read policy status
HSMM latest_asof target status
HSMM run atomicity status
probability readiness gate status
UI/analysis selector status
universe/data lineage status
evidence registry status
private path hygiene status
Stage03PreflightVerdict
BlockingPackages
DeferredPackages
```

## Pass criteria

To output `Stage03PreflightVerdict: PASS`, all must be true:

1. P0 packages pass.
2. WP8, WP9, WP10, and WP11 pass.
3. WP12 is either pass or explicitly deferred with no current UI exposure dependency.
4. UI and training entry points default to completed + lineage matched artifacts.
5. HMM cache read rejects legacy, mismatched, running, and causal-violating cache rows.
6. latest_asof targets do not use post-cutoff realized outcomes.
7. raw/calibrated `p_exit` does not bypass readiness gates.
8. No private DB/WAL is committed.
9. No external data fetch is used.
10. No HMM/HSMM training algorithm changes are introduced by the preflight packages.

If any condition fails, output:

```text
Stage03PreflightVerdict: BLOCKED
BlockingPackages: [...]
```

## Required validation

```bash
git diff --check
bash scripts/stage03_preflight_gate.sh
```

If local dependencies are complete, also run:

```bash
pytest -q
```

## Index update

If final verdict is PASS:

```text
mark WP0-WP13 according to accepted/deferred status
no true Stage03 package should be activated in this PR unless separately requested
```

If final verdict is BLOCKED:

```text
keep blocking packages active or reopen as needed
record exact BlockingPackages
```

## PR return format

```text
WP: STAGE03PF-WP13
status: pass / partial / fail
branch: stage03pf/wp13-stage03-preflight-gate
PR: ...
commands run:
- ...
Stage03PreflightVerdict: PASS / BLOCKED
BlockingPackages:
- ...
DeferredPackages:
- ...
P0 status:
- ...
P1 status:
- ...
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```