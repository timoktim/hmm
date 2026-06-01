# CODEX_THREAD_C_RECOVER_WP_C

Repository: timoktim/hmm
Assigned index_id: STAGE00-WP-C-v1
Work package: docs/work_packages/stage_00/STAGE00_WP_C_ui_readiness_causal_boundary.md

## Situation

The GitHub `main` branch did not initially contain the V0 source. The V0 baseline source currently exists in PR #1 / branch:

```text
stage00/wp-a-evidence-registry
```

PR #1 imports the V0 baseline source and implements WP-A. Until PR #1 is merged, `main` is not a valid starting point for WP-C implementation.

## Correct starting point

Preferred path:

1. Wait until PR #1 is merged into `main`.
2. Start a new branch from updated `main`:

```text
stage00/wp-c-ui-readiness
```

3. Execute only:

```text
docs/work_packages/stage_00/STAGE00_WP_C_ui_readiness_causal_boundary.md
```

Temporary stacked path if asked to proceed before PR #1 merges:

1. Branch from `stage00/wp-a-evidence-registry`, not from old `main`.
2. Name branch:

```text
stage00/wp-c-ui-readiness-stacked-on-wp-a
```

3. Clearly state in the PR body that it is stacked on PR #1 and must be rebased after PR #1 is merged.

## Scope

WP-C must implement UI readiness and causal boundary only:

- `src/ui/readiness_policy.py`
- `src/ui/causal_boundary.py`
- `src/ui/evidence_badges.py` if useful
- `tests/test_ui_readiness_policy.py`
- `tests/test_ui_causal_boundary.py`
- `reports/ui_readiness/stage00_wp_c_readiness_audit.md`
- `reports/ui_readiness/stage00_wp_c_readiness_audit.json`

Do not implement WP-B baseline freeze. Do not modify HMM/HSMM training algorithms. Do not fetch new data. Do not expose numeric HSMM `p_exit` unless readiness explicitly allows it.

## Required behavior

- HMM posterior must be treated as state confidence only, not as rising/falling/profit probability.
- Strategy/backtest UI must require causal walk-forward cache or be downgraded to research-only/block.
- Lifecycle UI must not display raw/calibrated numeric `p_exit` by default.
- Low/medium/high HSMM exit tendency can be displayed only as internal ordinal tendency.
- next-state tendency must be described as realized historical tendency, not predicted probability.
- Missing metadata must produce conservative warnings rather than silent pass.

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
pytest -q tests/test_lifecycle_ui_text_policy.py tests/test_lifecycle_text_audit_summary.py
pytest -q -m "not slow"
```

If DB exists, also run the readiness audit required by the work package. If DB is missing, mark the audit as `skipped_db_missing`.

## Return format

```text
Thread: C
index_id: STAGE00-WP-C-v1
starting point used: updated main / stacked on stage00/wp-a-evidence-registry
branch: ...
PR: ...
status: pass / partial / fail
commands run:
- ...
results:
- ...
UI pages changed:
- ...
readiness audit:
- report: ...
- numeric p_exit displayed: yes/no
- causal/in_sample mix found: yes/no
DB found: yes/no
external data fetch: no
training algorithm modified: no
WP-B baseline freeze implemented: no
risks:
- ...
```
